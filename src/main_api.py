"""
FastAPI application configuration and main entry point.
Handles routing, middleware, and application lifecycle.
"""

import os
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

# Initialize FastAPI app
app = FastAPI(
    title="Plex Manager",
    description="Unified media request and automation system",
    version="0.1.0"
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

# Include auth router
app.include_router(auth_router)

# Startup event - Initialize database
@app.on_event("startup")
async def startup_event():
    """Initialize database on application startup."""
    print("Starting Plex Manager API...")
    init_db()
    print("API ready!")


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
