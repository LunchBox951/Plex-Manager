from src.main_api import app

print("\n=== ALL ROUTES WITH 'requests' OR 'by-media' ===")
for route in app.routes:
    if hasattr(route, 'path'):
        if 'by-media' in route.path or 'requests' in route.path:
            methods = route.methods if hasattr(route, 'methods') else 'N/A'
            print(f"{methods} {route.path}")
            if hasattr(route, 'endpoint'):
                print(f"  -> {route.endpoint.__module__}.{route.endpoint.__name__}")
