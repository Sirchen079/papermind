import os

# Force litellm to use its bundled local model-cost map instead of fetching a
# remote JSON on import. Must run before any `import litellm` (triggered by the
# router imports below) so startup has no network dependency or latency spike.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from contextlib import asynccontextmanager  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi import FastAPI  # noqa: E402

from app.api.health import router as health_router  # noqa: E402
from app.api.models_api import router as models_router
from app.api.providers_api import router as providers_router
from app.api.settings_api import router as settings_router
from app.api.usage_api import router as usage_router
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
    app.include_router(settings_router, prefix="/api")
    app.include_router(providers_router, prefix="/api")
    app.include_router(models_router, prefix="/api")
    app.include_router(usage_router, prefix="/api")
    return app
