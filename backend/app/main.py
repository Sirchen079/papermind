import os

# Force litellm to use its bundled local model-cost map instead of fetching a
# remote JSON on import. Must run before any `import litellm` (triggered by the
# router imports below) so startup has no network dependency or latency spike.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from contextlib import asynccontextmanager  # noqa: E402
from html import escape  # noqa: E402
from threading import RLock

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from starlette.middleware.trustedhost import TrustedHostMiddleware  # noqa: E402

from app import paths  # noqa: E402

from app.api.archive_api import router as archive_router  # noqa: E402
from app.api.chat_api import router as chat_router  # noqa: E402
from app.api.claims_api import router as claims_router  # noqa: E402
from app.api.experiments_api import router as experiments_router  # noqa: E402
from app.api.graph_api import router as graph_router  # noqa: E402
from app.api.health import router as health_router  # noqa: E402
from app.api.ideas_api import router as ideas_router
from app.api.library_diagnostics_api import router as library_diagnostics_router
from app.api.models_api import router as models_router
from app.api.organization_api import router as organization_router
from app.api.papers_api import router as papers_router
from app.api.providers_api import router as providers_router
from app.api.radar_api import router as radar_router
from app.api.reading_api import router as reading_router
from app.api.readiness_api import router as readiness_router
from app.api.reports_api import router as reports_router
from app.api.research_progress_api import router as research_progress_router
from app.api.settings_api import router as settings_router
from app.api.skills_api import router as skills_router
from app.api.suggestions_api import router as suggestions_router
from app.api.thesis_api import router as thesis_router
from app.api.usage_api import router as usage_router
from app.api.research_api import router as research_router
from app.api.workspaces_api import router as workspaces_router
from app.api.shared_connections_api import router as shared_connections_router
from app.api.wiki_api import router as wiki_router
from app.logging_setup import configure_logging
from app.security.local_token import get_or_create_token


def inject_local_token(html: str, token: str) -> str:
    """Insert the token ``<meta>`` tag before the first ``</head>``.

    Returns ``html`` unchanged when there is no ``</head>`` to anchor on.
    The token is HTML-escaped (it lands inside a double-quoted attribute).
    """
    idx = html.find("</head>")
    if idx == -1:
        return html
    meta = f'<meta name="papermind-local-token" content="{escape(token, quote=True)}">'
    return html[:idx] + meta + html[idx:]


_migration_lock = RLock()


def _run_migrations() -> None:
    # Alembic's module-level environment is shared; concurrent project setup
    # must not bind it to another database halfway through an upgrade.
    with _migration_lock:
        _upgrade_database()


def _upgrade_database() -> None:
    """Apply Alembic migrations to the configured DB (upgrade to head)."""
    from alembic import command
    from alembic.config import Config

    from app.config import get_settings

    cfg = Config(str(paths.alembic_ini()))
    # The desktop host owns its rotating log. Alembic's console-only config
    # otherwise discards it (windowed executables have no visible stderr).
    cfg.attributes["configure_logger"] = False
    cfg.set_main_option("script_location", str(paths.migrations_dir()))
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{settings.resolved_db_path}")
    # Capture a consistent WAL-aware database copy before changing an existing
    # schema. New project databases require no backup; repeat starts at head
    # create none. The original key and PDFs remain in place throughout.
    if settings.resolved_db_path.is_file():
        import sqlite3
        from contextlib import closing
        from alembic.script import ScriptDirectory
        from uuid import uuid4
        with closing(sqlite3.connect(settings.resolved_db_path)) as source:
            version=source.execute("SELECT name FROM sqlite_master WHERE name='alembic_version'").fetchone()
            current=source.execute('SELECT version_num FROM alembic_version').fetchone() if version else None
            head=ScriptDirectory.from_config(cfg).get_current_head()
            if current is None or current[0]!=head:
                backup_dir=settings.data_dir/'backups'
                backup_dir.mkdir(parents=True,exist_ok=True)
                backup=backup_dir/f'schema-before-{uuid4().hex}.sqlite'
                with closing(sqlite3.connect(backup)) as destination:
                    source.backup(destination)
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


def _create_app() -> FastAPI:
    configure_logging()
    from app.db.engine import get_engine
    from app.config import get_settings
    from app.ingestion.pdf_storage import finish_restore
    from app.research.service import recover_interrupted
    from app.workspaces.registry import WorkspaceRegistry
    from app.workspaces.context import bind_workspace
    from app.workspaces.middleware import WorkspaceMiddleware
    registry = WorkspaceRegistry(get_settings())
    for workspace in registry.list():
        try:
            registry.validate_existing(workspace['id'])
            with bind_workspace(registry.context(workspace['id'])):
                _run_migrations()
                _load_default_skills()
                finish_restore(get_engine(), get_settings().data_dir)
                recover_interrupted(get_engine())
                from app.wiki.service import recover_interrupted as recover_wiki
                recover_wiki(get_engine())
            registry.mark_ready(workspace['id'])
        except Exception:
            # One project's damaged/missing database must not disable healthy
            # projects. Preserve its files and expose a recoverable state.
            import logging
            logging.getLogger(__name__).exception('Workspace startup failed: %s', workspace['id'])
            reason = registry.unavailable_reason(workspace['id'])
            registry.mark_unavailable(workspace['id'], reason or '项目初始化未完成，请检查应用日志和磁盘状态，恢复备份后重新启动。')

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Literature radar (P10.2): opportunistic pull of due subscriptions in
        # the background — non-blocking, errors swallowed, no-op in tests.
        from app.radar.service import start_background_refresh

        for workspace in registry.list():
            if not workspace['archived'] and workspace['available']:
                with bind_workspace(registry.context(workspace['id'])):
                    start_background_refresh()
        try:
            yield
        finally:
            app.state.release_runtime_lease()

    app = FastAPI(title="PaperMind", version="0.5.3", lifespan=lifespan)
    from app.security.crypto import MissingKeyError
    from fastapi.responses import JSONResponse

    @app.exception_handler(MissingKeyError)
    async def missing_key_handler(request, exc):
        return JSONResponse(status_code=409, content={'detail': str(exc)})

    from threading import Lock
    app.state.application_downloads = {}
    app.state.application_download_lock = Lock()
    app.state.workspaces = registry
    app.add_middleware(WorkspaceMiddleware, registry=registry)

    # Host 头白名单（P15）：仅放行本机开发/测试来源。Starlette 在比对前
    # 对 Host 做 split(":")[0] 剥端口，故裸主机名即端口无关；非法 Host
    # 一律 400 "Invalid host header"。注意 [::1] 等 IPv6 字面量会被
    # split 截成 "["，属 starlette 实现限制，无法经允许列表放行。
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )

    app.include_router(health_router, prefix="/api")
    app.include_router(workspaces_router, prefix="/api")
    app.include_router(shared_connections_router, prefix="/api")
    app.include_router(wiki_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(providers_router, prefix="/api")
    app.include_router(models_router, prefix="/api")
    app.include_router(usage_router, prefix="/api")
    app.include_router(research_router, prefix="/api")
    app.include_router(papers_router, prefix="/api")
    app.include_router(claims_router, prefix="/api")
    app.include_router(reading_router, prefix="/api")
    app.include_router(readiness_router, prefix="/api")
    app.include_router(research_progress_router, prefix="/api")
    app.include_router(library_diagnostics_router, prefix="/api")
    app.include_router(organization_router, prefix="/api")
    app.include_router(ideas_router, prefix="/api")
    app.include_router(experiments_router, prefix="/api")
    app.include_router(thesis_router, prefix="/api")
    app.include_router(graph_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    app.include_router(skills_router, prefix="/api")
    app.include_router(suggestions_router, prefix="/api")
    app.include_router(radar_router, prefix="/api")
    app.include_router(reports_router, prefix="/api")
    app.include_router(archive_router, prefix="/api")

    # Serve the built frontend (production single-app mode) when present.
    # API routes are registered above with the /api prefix, so they take
    # precedence over this catch-all static mount.
    dist = paths.frontend_dist()

    # Explicit GET "/" (P16): serve index.html with the local token injected
    # as a <meta> tag so the SPA receives it on first load. Registered as a
    # regular route *before* the StaticFiles mount below — Starlette matches
    # routes in order, so this exact-path handler wins over the mount for "/",
    # while every other asset request (/assets/..., /pdfjs/...) still falls
    # through to the mount untouched. index.html is read once here (startup
    # cache); no per-request disk access. When dist/index.html is absent the
    # route is not registered at all and behavior stays exactly as before.
    index_file = dist / "index.html"
    if index_file.is_file():
        index_response = HTMLResponse(
            inject_local_token(
                index_file.read_text(encoding="utf-8"),
                get_or_create_token(),
            )
        )

        @app.get("/", include_in_schema=False)
        async def serve_index() -> HTMLResponse:
            return index_response

    if dist.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")

    return app


def create_app() -> FastAPI:
    from app.config import get_settings
    from app.workspaces.runtime_lease import RuntimeLease
    import weakref
    lease = RuntimeLease(get_settings().data_dir.resolve())
    try:
        if (get_settings().data_dir / '.application-restore.json').is_file():
            raise OSError('上次整体恢复尚未完成。请保留数据目录中的恢复记录，重新执行整体恢复或使用记录中的回退副本。')
        app = _create_app()
    except BaseException:
        lease.close()
        raise
    # Test clients that do not enter lifespan still release on collection.
    release = weakref.finalize(app, lease.close)
    app.state.release_runtime_lease = release
    return app
