"""
FastAPI application configuration and main entry point.
Handles routing, middleware, and application lifecycle.
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from src.database import init_db
from src.auth import router as auth_router, get_current_user
from src.downloads import router as downloads_router
from src.download_monitor import start_monitor, stop_monitor


# Validate required environment variables
def validate_environment():
    """Validate that all required environment variables are set."""
    required_vars = [
        'PLEX_URL',
        'ENCRYPTION_KEY',
        'JWT_SECRET_KEY',
        'DOWNLOADS_PATH',
        'MOVIES_PATH',
        'TV_PATH',
        'QBITTORRENT_URL',
        'QBITTORRENT_USERNAME',
        'QBITTORRENT_PASSWORD'
    ]
    
    missing = []
    for var in required_vars:
        if not os.getenv(var):
            missing.append(var)
    
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
    
    # Verify paths exist
    paths_to_check = {
        'DOWNLOADS_PATH': os.getenv('DOWNLOADS_PATH'),
        'MOVIES_PATH': os.getenv('MOVIES_PATH'),
        'TV_PATH': os.getenv('TV_PATH')
    }
    
    missing_paths = []
    for name, path in paths_to_check.items():
        if path and not os.path.exists(path):
            missing_paths.append(f"{name}: {path}")
    
    if missing_paths:
        raise ValueError(f"Required paths do not exist:\n" + "\n".join(missing_paths))
    
    print("✓ All environment variables validated")
    print(f"✓ Downloads path: {os.getenv('DOWNLOADS_PATH')}")
    print(f"✓ Movies path: {os.getenv('MOVIES_PATH')}")
    print(f"✓ TV path: {os.getenv('TV_PATH')}")


# Application lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""
    # Startup
    print("Starting Plex Manager API...")
    
    # Validate environment
    validate_environment()
    
    # Initialize database
    init_db()
    
    # Start download monitor
    start_monitor()
    
    print("API ready!")
    
    yield
    
    # Shutdown
    print("Shutting down Plex Manager API...")
    stop_monitor()
    print("Shutdown complete")


# Initialize FastAPI app with lifespan
app = FastAPI(
    title="Plex Manager",
    description="Unified media request and automation system",
    version="0.1.0",
    lifespan=lifespan
)

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security Headers Middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup Jinja2 templates
templates = Jinja2Templates(directory="templates")

# Include routers
app.include_router(auth_router)
app.include_router(downloads_router, prefix="/api", tags=["downloads"])


# Root route - Landing page
@app.get("/", response_class=HTMLResponse)
@limiter.limit("10/minute")
async def landing_page(request: Request):
    """
    Serve landing page or redirect to dashboard if already authenticated.
    """
    # Check if user is authenticated
    try:
        token = request.cookies.get("session_token")
        if token:
            # Try to validate token
            from src.database import SessionLocal
            db = SessionLocal()
            try:
                user = await get_current_user(request, db)
                if user:
                    return RedirectResponse(url="/dashboard", status_code=302)
            except:
                pass
            finally:
                db.close()
    except:
        pass
    
    return templates.TemplateResponse("landing.html", {"request": request})


# Dashboard route
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """
    Serve dashboard for authenticated users.
    Redirects to landing page if not authenticated.
    """
    try:
        from src.database import SessionLocal
        db = SessionLocal()
        try:
            user = await get_current_user(request, db)
            print(f"Dashboard accessed by user: {user.username}")
            return templates.TemplateResponse(
                "dashboard.html",
                {"request": request, "user": user}
            )
        finally:
            db.close()
    except Exception as e:
        print(f"Dashboard access failed: {e}")
        import traceback
        traceback.print_exc()
        return RedirectResponse(url="/", status_code=302)


# Health check endpoint
@app.get("/api/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "service": "Plex Manager API",
        "version": "0.1.0"
    }
