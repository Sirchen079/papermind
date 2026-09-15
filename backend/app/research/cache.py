"""Exact validated-result reuse, with bounded storage and concurrent coalescing."""
import hashlib
import json
import threading
from datetime import datetime, timedelta, timezone
from sqlmodel import Session, select
from sqlalchemy import delete
from app.models import AIResultCache

CACHE_VERSION = 'research-v2-stable-input'
TTL = timedelta(days=7)
MAX_ENTRIES = 500
_locks = [threading.Lock() for _ in range(64)]


def cache_key(provider, model, prompt, system_prompt):
    # Include endpoint, credentials and protocol: changing an account/model or
    # material version must never reuse another provider's result.
    scope = {name: getattr(provider, name, None) for name in ('id', 'type', 'base_url', 'api_key_encrypted', 'extra_headers_json')}
    body = json.dumps([CACHE_VERSION, scope, model, prompt, system_prompt, 2400, 'low'], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


def key_lock(key):
    return _locks[int(key[:8], 16) % len(_locks)]


def read(engine, key):
    with Session(engine) as session:
        row = session.get(AIResultCache, key)
        if row is None or row.created_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc) - TTL:
            return None
        try:
            return json.loads(row.result_json)
        except (TypeError, ValueError):
            return None


def write(engine, key, result):
    with Session(engine) as session:
        now = datetime.now(timezone.utc)
        session.exec(delete(AIResultCache).where(AIResultCache.created_at < now - TTL))
        old = session.get(AIResultCache, key)
        if old:
            old.result_json = json.dumps(result, ensure_ascii=False)
            old.created_at = now
            session.add(old)
        else:
            session.add(AIResultCache(key=key, result_json=json.dumps(result, ensure_ascii=False), created_at=now))
        session.flush()
        stale = session.exec(select(AIResultCache.key).order_by(AIResultCache.created_at.desc()).offset(MAX_ENTRIES)).all()
        if stale:
            session.exec(delete(AIResultCache).where(AIResultCache.key.in_(stale)))
        session.commit()
