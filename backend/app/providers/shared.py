"""Shared connection credentials, project-local selection and usage identity.

A project stores a reference and keeps its own Provider primary key for usage
foreign keys. Resolve returns a detached provider/crypto pair, never changing
another project's database or holding a transaction over a model call.
"""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import sqlite3

from sqlmodel import Session, select
from app.models import Model, Provider
from app.security.crypto import _build_crypto, get_crypto
from app.workspaces.context import current_workspace


class SharedConflict(ValueError):
    pass


def application_dir():
    context=current_workspace.get()
    if context and context.application_dir:
        return context.application_dir
    from app.config import Settings
    return Settings().data_dir.resolve()


@contextmanager
def store():
    root=application_dir()
    root.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(root/'connections.sqlite',timeout=30)) as db:
        db.row_factory=sqlite3.Row
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS connection ('
                       'id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, '
                       'base_url TEXT, api_key_encrypted TEXT, extra_headers_json TEXT, '
                       'enabled INTEGER NOT NULL, models_json TEXT NOT NULL, '
                       'version INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL)')
            yield db


def shared_crypto():
    from app.security.crypto import require_recoverable_key
    require_recoverable_key(application_dir()/'connections.key', application_dir()/'connections.sqlite', 'connection')
    return _build_crypto(str(application_dir()/'connections.key'))


def get(connection_id):
    with store() as db:
        row=db.execute('SELECT * FROM connection WHERE id=?',(connection_id,)).fetchone()
    if row is None:
        raise LookupError('共享连接不存在；请重新关联或改用项目专用连接')
    return dict(row)


def public(row):
    return {**{key:row[key] for key in ('id','name','type','base_url','enabled','version','updated_at')},
            'models':json.loads(row['models_json'])}


def list_connections():
    with store() as db:
        return [public(dict(row)) for row in db.execute('SELECT * FROM connection ORDER BY name,id')]


def resolve(provider):
    if not provider.shared_connection_id:
        return provider.model_copy(), get_crypto()
    row=get(provider.shared_connection_id)
    if row['api_key_encrypted'] and not (application_dir()/'connections.key').is_file():
        raise LookupError('共享连接的密钥文件缺失，请恢复应用配置或重新配置连接')
    actual=provider.model_copy(update={key:row[key] for key in ('name','type','base_url','api_key_encrypted','extra_headers_json')})
    actual.enabled=provider.enabled and bool(row['enabled']) and not provider.is_deleted
    return actual, shared_crypto()


def publish(session, provider):
    if provider.shared_connection_id:
        return public(get(provider.shared_connection_id))
    models=[{k:getattr(m,k) for k in ('model_id','display_name','context_window','role_default')}
            for m in session.exec(select(Model).where(Model.provider_id==provider.id)).all()]
    # Stable across an uncertain response/retry; changes to the source create a
    # distinct publication, rather than overwriting an existing shared entry.
    identity=[str(session.get_bind().url),provider.model_dump(mode='json'),models]
    connection_id=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:32]
    key=get_crypto().decrypt(provider.api_key_encrypted) if provider.api_key_encrypted else None
    encrypted=shared_crypto().encrypt(key) if key is not None else None
    with store() as db:
        db.execute('INSERT OR IGNORE INTO connection(id,name,type,base_url,api_key_encrypted,extra_headers_json,enabled,models_json,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                   (connection_id,provider.name,provider.type,provider.base_url,encrypted,provider.extra_headers_json,provider.enabled,json.dumps(models),datetime.now(timezone.utc).isoformat()))
    provider.shared_connection_id=connection_id
    session.add(provider);session.commit()
    return public(get(connection_id))


def attach(session, connection_id):
    row=get(connection_id)
    if not row['enabled']:
        raise ValueError('共享连接已停用，请先启用或选择其他连接')
    # Serialize the small local mutation: two windows attaching the same entry
    # simultaneously must not duplicate providers or default model roles.
    session.connection().exec_driver_sql('BEGIN IMMEDIATE')
    existing=session.exec(select(Provider).where(Provider.shared_connection_id==connection_id,Provider.is_deleted==False)).first()
    if existing:
        session.commit();return existing
    key=shared_crypto().decrypt(row['api_key_encrypted']) if row['api_key_encrypted'] else None
    provider=Provider(name=row['name'],type=row['type'],base_url=row['base_url'],
                      shared_connection_id=connection_id,extra_headers_json=row['extra_headers_json'],
                      api_key_encrypted=get_crypto().encrypt(key) if key is not None else None)
    session.add(provider);session.flush()
    assigned={m.role_default for m in session.exec(select(Model)).all() if m.role_default}
    for data in json.loads(row['models_json']):
        data=dict(data)
        if data.get('role_default') in assigned:data['role_default']=None
        if data.get('role_default'):assigned.add(data['role_default'])
        session.add(Model(provider_id=provider.id,is_manual=True,**data))
    session.commit();session.refresh(provider)
    return provider


def detach(session, provider):
    actual, crypto=resolve(provider)
    key=crypto.decrypt(actual.api_key_encrypted) if actual.api_key_encrypted else None
    for name in ('name','type','base_url','extra_headers_json'):
        setattr(provider,name,getattr(actual,name))
    provider.api_key_encrypted=get_crypto().encrypt(key) if key is not None else None
    provider.shared_connection_id=None
    session.add(provider);session.commit();session.refresh(provider)
    return provider


def update(connection_id, expected_version, changes):
    with store() as db:
        db.execute('BEGIN IMMEDIATE')
        found=db.execute('SELECT * FROM connection WHERE id=?',(connection_id,)).fetchone()
        if found is None:raise LookupError('共享连接不存在')
        row=dict(found)
        if row['version']!=expected_version:
            raise SharedConflict('共享连接已有更新，请刷新后核对')
        for name in ('name','base_url','enabled'):
            if name in changes:row[name]=changes[name]
        if 'api_key' in changes:
            row['api_key_encrypted']=shared_crypto().encrypt(changes['api_key'])
        if row['type']=='openai_compat' and not row['base_url']:
            raise ValueError('自定义连接需要 API 地址')
        db.execute('UPDATE connection SET name=?,base_url=?,enabled=?,api_key_encrypted=?,version=version+1,updated_at=? WHERE id=?',
                   (row['name'],row['base_url'],row['enabled'],row['api_key_encrypted'],datetime.now(timezone.utc).isoformat(),connection_id))
    return public(get(connection_id))


def materialize_backup(snapshot):
    """Export a project as self-contained connections, preserving live references."""
    warnings=[]
    from cryptography.fernet import InvalidToken
    with Session(snapshot) as session:
        for provider in session.exec(select(Provider).where(Provider.shared_connection_id!=None)).all():
            try:
                detach(session,provider)
            except (LookupError, ValueError, InvalidToken):
                provider.enabled=False
                provider.shared_connection_id=None
                session.add(provider);session.commit()
                warnings.append(f'连接 {provider.id} 的共享配置不可用，恢复副本中已停用')
    return warnings
