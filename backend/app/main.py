import os

# Force litellm to use its bundled local model-cost map instead of fetching a
# remote JSON on import. Must run before any `import litellm` (triggered by the
# router imports below) so startup has no network dependency or latency spike.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI  # noqa: E402

from app import paths  # noqa: E402

from app.api.archive_api import router as archive_router  # noqa: E402
from app.api.chat_api import router as chat_router  # noqa: E402
from app.api.graph_api import router as graph_router  # noqa: E402
from app.api.health import router as health_router  # noqa: E402
from app.api.library_diagnostics_api import router as library_diagnostics_router
from app.api.models_api import router as models_router
from app.api.organization_api import router as organization_router
from app.api.papers_api import router as papers_router
from app.api.providers_api import router as providers_router
from app.api.reading_api import router as reading_router
from app.api.readiness_api import router as readiness_router
from app.api.research_progress_api import router as research_progress_router
from app.api.settings_api import router as settings_router
from app.api.skills_api import router as skills_router
from app.api.suggestions_api import router as suggestions_router
from app.api.thesis_api import router as thesis_router
from app.api.usage_api import router as usage_router
from app.logging_setup import configure_logging


def _run_migrations() -> None:
    """Apply Alembic migrations to the configured DB (upgrade to head)."""
    from alembic import command
    from alembic.config import Config

    from app.config import get_settings

    cfg = Config(str(paths.alembic_ini()))
    cfg.set_main_option("script_location", str(paths.migrations_dir()))
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{settings.resolved_db_path}")
    command.upgrade(cfg, "head")


def _load_default_skills() -> None:
    """Insert bundled ``user_skills/*.md`` that aren't yet in the DB.

    Insert-only (``overwrite=False``) so a bundled skill the user edited in the
    UI is preserved across restarts. Ensures a fresh install has its bundled
    skills available in chat without a manual 'reload' click. Skipped when
    ``PAPERMIND_NO_AUTOLOAD_SKILLS`` is set — tests want a clean skill table.
    """
    if os.environ.get("PAPERMIND_NO_AUTOLOAD_SKILLS"):
        return
    from sqlmodel import Session

    from app.api.skills_api import default_skills_dir
    from app.db.engine import get_engine
    from app.skills.loader import load_skills_from_dir

    with Session(get_engine()) as session:
        load_skills_from_dir(session, default_skills_dir(), overwrite=False)


def create_app() -> FastAPI:
    configure_logging()
    _run_migrations()
    _load_default_skills()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    app = FastAPI(title="PaperMind", lifespan=lifespan)
    app.include_router(health_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(providers_router, prefix="/api")
    app.include_router(models_router, prefix="/api")
    app.include_router(usage_router, prefix="/api")
    app.include_router(papers_router, prefix="/api")
    app.include_router(reading_router, prefix="/api")
    app.include_router(readiness_router, prefix="/api")
    app.include_router(research_progress_router, prefix="/api")
    app.include_router(library_diagnostics_router, prefix="/api")
    app.include_router(organization_router, prefix="/api")
    app.include_router(thesis_router, prefix="/api")
    app.include_router(graph_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    app.include_router(skills_router, prefix="/api")
    app.include_router(suggestions_router, prefix="/api")
    app.include_router(archive_router, prefix="/api")

    # Serve the built frontend (production single-app mode) when present.
    # API routes are registered above with the /api prefix, so they take
    # precedence over this catch-all static mount.
    dist = paths.frontend_dist()
    if dist.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")

    return app
