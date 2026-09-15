"""Shared FastAPI dependencies (single import point for routers)."""
from app.db.engine import get_session  # noqa: F401  (re-exported)
