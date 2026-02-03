"""
Plex OAuth authentication and JWT token management.
Implements PIN-based OAuth flow for Plex authentication.
"""

import os
from datetime import datetime, timedelta
from typing import Optional
import requests
from fastapi import APIRouter, Depends, HTTPException, Response, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from plexapi.myplex import MyPlexAccount

from src.database import get_db
from src.models import User, Permission
from src.encryption import get_encryption
from src.plex import is_plex_server_owner

# Router for auth endpoints
router = APIRouter()

# Security
security = HTTPBearer(auto_error=False)

# JWT Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7

# Plex OAuth Configuration
PLEX_CLIENT_ID = os.getenv("PLEX_CLIENT_ID")
if not PLEX_CLIENT_ID:
    raise ValueError("PLEX_CLIENT_ID environment variable not set")


def create_jwt_token(user: User) -> str:
    """Create JWT token for authenticated user."""
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode = {
        "sub": str(user.id),
        "plex_id": user.plex_id,
        "username": user.username,
        "exp": expire
    }
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def set_auth_cookie(response: Response, token: str):
    """Set httpOnly authentication cookie."""
    is_production = os.getenv("ENV", "development") == "production"
    
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=is_production,  # HTTPS only in production
        samesite="strict",
        max_age=ACCESS_TOKEN_EXPIRE_DAYS * 24 * 60 * 60  # 7 days in seconds
    )


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
) -> User:
    """
    Dependency to get current authenticated user from cookie.
    Raises 401 if not authenticated.
    """
    # Get token from cookie
    token = request.cookies.get("session_token")
    
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    # Get user from database
    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    
    return user


async def require_admin(
    request: Request,
    db: Session = Depends(get_db)
) -> User:
    """
    Dependency to require admin privileges.
    Raises 403 if user is not an admin.
    """
    user = await get_current_user(request, db)
    
    if not user.is_admin():
        raise HTTPException(status_code=403, detail="Admin privileges required")
    
    return user


@router.get("/api/auth/start")
async def start_auth():
    """
    Generate a Plex PIN and return the PIN ID and auth URL.
    Used by the frontend to initiate authentication.
    """
    print("Generating Plex PIN for authentication...")
    
    try:
        response = requests.post(
            "https://plex.tv/api/v2/pins",
            headers={
                "accept": "application/json",
                "X-Plex-Client-Identifier": PLEX_CLIENT_ID
            },
            data={"strong": "true"}
        )
        response.raise_for_status()
        pin_data = response.json()
        
        print(f"Generated PIN: {pin_data['code']}, ID: {pin_data['id']}")
        
        # Build Plex OAuth URL with properly formatted context
        auth_url = (
            f"https://app.plex.tv/auth#"
            f"?clientID={PLEX_CLIENT_ID}"
            f"&code={pin_data['code']}"
            f"&forwardUrl=http://localhost:8000"
        )
        
        print(f"Auth URL: {auth_url}")
        
        return {
            "pin_id": pin_data['id'],
            "auth_url": auth_url
        }
    
    except Exception as e:
        print(f"Error generating PIN: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate Plex PIN")


@router.get("/auth/login")
async def login(request: Request):
    """
    Initiate Plex OAuth flow by generating a PIN.
    Returns auth popup page that handles the OAuth flow.
    """
    print("Initiating Plex OAuth login...")
    
    # Generate Plex PIN
    try:
        response = requests.post(
            "https://plex.tv/api/v2/pins",
            headers={
                "accept": "application/json",
                "X-Plex-Client-Identifier": PLEX_CLIENT_ID
            },
            data={"strong": "true"}
        )
        response.raise_for_status()
        pin_data = response.json()
        
        print(f"Generated PIN: {pin_data['code']}, ID: {pin_data['id']}")
        
        # Build Plex OAuth URL
        # The user needs to navigate to this URL to authorize the PIN
        auth_url = (
            f"https://app.plex.tv/auth#?"
            f"clientID={PLEX_CLIENT_ID}&"
            f"code={pin_data['code']}&"
            f"context%5Bdevice%5D%5Bproduct%5D=Plex%20Manager"
        )
        
        print(f"OAuth URL: {auth_url}")
        
        # Return auth popup template with PIN ID and auth URL
        from src.main_api import templates
        return templates.TemplateResponse(
            "auth_popup.html",
            {
                "request": request,
                "auth_url": auth_url,
                "pin_id": pin_data['id']
            }
        )
    
    except Exception as e:
        print(f"Error generating PIN: {e}")
        raise HTTPException(status_code=500, detail="Failed to initiate Plex login")


@router.get("/api/auth/poll/{pin_id}")
async def poll_pin(pin_id: str, db: Session = Depends(get_db)):
    """
    Poll Plex PIN status to check if user has authenticated.
    Returns success with redirect URL when auth is complete.
    """
    
    try:
        # Check PIN status
        response = requests.get(
            f"https://plex.tv/api/v2/pins/{pin_id}",
            headers={
                "accept": "application/json",
                "X-Plex-Client-Identifier": PLEX_CLIENT_ID
            }
        )
        response.raise_for_status()
        pin_data = response.json()
        
        # Check if auth token is available
        auth_token = pin_data.get("authToken")
        if not auth_token:
            # Still pending - user hasn't authenticated yet
            return JSONResponse({"status": "pending"})
        
        print(f"PIN {pin_id} authenticated successfully!")
        
        # Get Plex user info
        account = MyPlexAccount(token=auth_token)
        print(f"Plex user: {account.username} (ID: {account.id})")
        
        # Encrypt Plex token
        encryption = get_encryption()
        encrypted_token = encryption.encrypt(auth_token)
        
        # Check if user exists
        user = db.query(User).filter(User.plex_id == str(account.id)).first()
        
        if user:
            # Update existing user
            print(f"Updating existing user: {user.username}")
            user.last_login = datetime.utcnow()
            user.encrypted_plex_token = encrypted_token
            
            # Check if user is server owner and update permissions
            is_owner = is_plex_server_owner(auth_token)
            if is_owner:
                if not user.has_permission(Permission.ADMIN):
                    print(f"Server owner detected - granting admin privileges to {user.username}")
                    user.permissions = Permission.ADMIN
            else:
                # Ensure non-owners only have request permissions
                if user.has_permission(Permission.ADMIN):
                    print(f"User {user.username} is no longer server owner - removing admin privileges")
                user.permissions = Permission.CAN_REQUEST
        else:
            # Create new user
            print(f"Creating new user: {account.username}")
            
            # Check if user is the server owner
            is_owner = is_plex_server_owner(auth_token)
            permissions = Permission.ADMIN if is_owner else Permission.CAN_REQUEST
            
            user = User(
                plex_id=str(account.id),
                username=account.username,
                email=account.email,
                avatar_url=account.thumb if hasattr(account, 'thumb') else None,
                encrypted_plex_token=encrypted_token,
                permissions=permissions
            )
            db.add(user)
            
            if is_owner:
                print(f"✓ Server owner detected - granted admin privileges to {account.username}")
            else:
                print(f"✗ Not server owner - granted request-only permissions to {account.username}")
        
        db.commit()
        db.refresh(user)
        
        # Create JWT token
        jwt_token = create_jwt_token(user)
        
        # Return success with token (cookie will be set by callback endpoint)
        return JSONResponse({
            "status": "success",
            "token": jwt_token,
            "user": user.to_dict()
        })
    
    except Exception as e:
        print(f"Error polling PIN: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.get("/auth/callback")
async def auth_callback(token: str, response: Response):
    """
    Handle OAuth callback by setting cookie.
    Token is passed from polling endpoint.
    """
    print("Setting auth cookie...")
    
    # Set httpOnly cookie
    set_auth_cookie(response, token)
    
    # Return JSON success response
    return {"status": "success", "message": "Authentication complete"}


@router.get("/api/auth/me")
async def get_me(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user)
):
    """
    Get current authenticated user.
    Refreshes JWT cookie if user is logged in.
    """
    # Refresh JWT token
    new_token = create_jwt_token(current_user)
    set_auth_cookie(response, new_token)
    
    return current_user.to_dict()


@router.post("/api/auth/logout")
async def logout(response: Response):
    """Logout by clearing the session cookie."""
    print("Logging out user...")
    
    response.delete_cookie(key="session_token")
    return {"message": "Logged out successfully"}
