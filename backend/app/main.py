from fastapi import FastAPI

from app.api.health import router as health_router
from app.logging_setup import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="PaperMind")
    app.include_router(health_router, prefix="/api")
    return app
