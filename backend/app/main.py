from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api.health import router as health_router
from app.logging_setup import configure_logging


def _run_migrations() -> None:
    """Apply Alembic migrations to the configured DB (upgrade to head)."""
    from alembic import command
    from alembic.config import Config

    from app.config import get_settings

    here = Path(__file__).resolve().parent.parent
    cfg = Config(str(here / "alembic.ini"))
    cfg.set_main_option("script_location", str(here / "migrations"))
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{settings.resolved_db_path}")
    command.upgrade(cfg, "head")


def create_app() -> FastAPI:
    configure_logging()
    _run_migrations()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    app = FastAPI(title="PaperMind", lifespan=lifespan)
    app.include_router(health_router, prefix="/api")
    return app
