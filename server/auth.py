"""
Веб-авторизация дашборда (session cookie).
API агентов по-прежнему использует X-API-Key на POST /api/*.
"""
import os
from urllib.parse import quote

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

AUTH_USERNAME = os.getenv("AUTH_USERNAME", "administrator")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "superwatcher")
SESSION_SECRET = os.getenv(
    "SESSION_SECRET",
    "sync-layer-dashboard-session-secret-change-me",
)

AGENT_POST_PATHS = {
    "/api/heartbeat",
    "/api/events",
    "/api/screenshot",
    "/api/processes",
    "/api/network",
    "/api/print",
}

PUBLIC_PATHS = {
    "/login",
    "/logout",
    "/api/health",
}


def _is_public(path: str, method: str) -> bool:
    if path.startswith("/static"):
        return True
    if path in PUBLIC_PATHS:
        return True
    if method == "POST" and path in AGENT_POST_PATHS:
        return True
    return False


def _is_authenticated(request: Request, api_key: str) -> bool:
    if request.session.get("authenticated"):
        return True
    if request.headers.get("x-api-key") == api_key:
        return True
    return False


class DashboardAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, api_key: str):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if _is_public(path, request.method):
            return await call_next(request)

        if _is_authenticated(request, self.api_key):
            return await call_next(request)

        if path.startswith("/api/") or path.startswith("/screenshots/api/"):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        next_path = quote(path)
        return RedirectResponse(url=f"/login?next={next_path}", status_code=303)
