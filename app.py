from dotenv import load_dotenv
import os
load_dotenv(os.path.join(os.path.dirname(__file__), "key.env"))

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from datetime import datetime
import uvicorn
import logging
import asyncio
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

from config import settings
from database import init_connection_pool, close_connection_pool, ensure_runtime_schema
from redis_client import init_redis_client, close_redis
from auth import router as auth_router
from user_profile import router as profile_router
from dashboard import router as dashboard_router
from payment import router as payment_router
from interview import router as interview_router
from pre_interview import router as pre_interview_router
from websocket_manager import ConnectionManager
from background_tasks import check_expired_subscriptions

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("interai")

_background_tasks = []

@asynccontextmanager
async def lifespan(app: FastAPI):

    init_connection_pool()
    ensure_runtime_schema()
    init_redis_client()

    task = asyncio.create_task(check_expired_subscriptions())
    _background_tasks.append(task)
    logger.info("Background subscription checker started")
    logger.info("Application started successfully")

    yield

    for task in _background_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    close_connection_pool()
    close_redis()
    logger.info("Application shutdown complete")

_docs_url = "/docs" if settings.ENVIRONMENT == "development" else None
_redoc_url = "/redoc" if settings.ENVIRONMENT == "development" else None

app = FastAPI(
    title="InterAI Backend",
    description="Backend for AI interview platform",
    version="2.0.0",
    lifespan=lifespan,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
)

ws_manager = ConnectionManager()
app.state.ws_manager = ws_manager

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: StarletteResponse = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred"}
    )

app.include_router(auth_router, prefix="/api/auth")
app.include_router(profile_router, prefix="/api/profile")
app.include_router(dashboard_router, prefix="/api/dashboard")
app.include_router(payment_router, prefix="/api/payment")
app.include_router(interview_router, prefix="/api/interview")
app.include_router(pre_interview_router)

@app.get("/health")
async def health():
    from database import get_db

    db_healthy = False
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
        db_healthy = True
    except Exception:
        pass

    redis_healthy = False
    try:
        from redis_client import get_redis_client
        redis_client = get_redis_client()
        if redis_client:
            redis_client.ping()
            redis_healthy = True
    except Exception:
        pass

    return {
        "status": "healthy" if db_healthy else "degraded",
        "time": datetime.utcnow().isoformat(),
        "checks": {
            "database": db_healthy,
            "redis": redis_healthy,
            "websocket_connections": ws_manager.get_active_users_count()
        }
    }

@app.get("/")
async def root():
    return {
        "service": "InterAI Backend",
        "version": "2.0.0",
        "status": "running"
    }

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=False,
        log_level="info"
    )
