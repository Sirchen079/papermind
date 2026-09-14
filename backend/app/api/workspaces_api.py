from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from uuid import UUID
from app.workspaces.context import current_workspace
from app.security.local_token import require_local_token

router = APIRouter()


class ApplicationBackupIn(BaseModel):
    request_id: UUID


@router.get('/workspaces/backups')
def application_backups(request: Request):
    from app.archive.application import list_backups
    return list_backups(request.app.state.workspaces)


@router.post('/workspaces/backups', status_code=201)
def backup_application(body: ApplicationBackupIn, request: Request):
    from app.archive.application import create_backup
    try:
        return create_backup(request.app.state.workspaces, body.request_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(409, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(503, '整体备份未完成，请检查磁盘空间与文件权限后重试。') from exc


@router.post('/workspaces/backups/{filename}/verify')
def verify_application_backup(filename: str, request: Request):
    from app.archive.application import resolve_backup, verify
    try:
        result = verify(resolve_backup(request.app.state.workspaces, filename))
        result.pop('manifest', None)
        return result
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get('/workspaces/backups/{filename}')
def download_application_backup(filename: str, request: Request, _: str = Depends(require_local_token)):
    from app.archive.application import resolve_backup
    try:
        path = resolve_backup(request.app.state.workspaces, filename)
        return FileResponse(path, media_type='application/zip', filename=path.name)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get('/workspaces/backups/{filename}/restore-guide')
def application_restore_guide(filename: str, request: Request):
    from app.archive.application import restore_guide
    try:
        return restore_guide(request.app.state.workspaces, filename)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post('/workspaces/backups/{filename}/download-ticket')
def application_download_ticket(filename: str, request: Request, _: str = Depends(require_local_token)):
    import secrets
    import time
    from app.archive.application import resolve_backup
    try:
        path = resolve_backup(request.app.state.workspaces, filename)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    with request.app.state.application_download_lock:
        tickets = request.app.state.application_downloads
        now = time.monotonic()
        for token in list(tickets):
            if tickets[token][1] < now:
                tickets.pop(token)
        if len(tickets) >= 1000:
            raise HTTPException(429, '下载请求过多，请稍后重试。')
        token = secrets.token_urlsafe(32)
        tickets[token] = (path, now + 300)
    return {'url': '/api/workspaces/backup-download/' + token}


@router.get('/workspaces/backup-download/{token}')
def application_ticket_download(token: str, request: Request):
    import time
    with request.app.state.application_download_lock:
        value = request.app.state.application_downloads.pop(token, None)
    if value is None or value[1] < time.monotonic() or not value[0].is_file():
        raise HTTPException(404, '下载链接已失效，请重新点击下载。')
    return FileResponse(value[0], media_type='application/zip', filename=value[0].name)


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    goal: str = Field(default='', max_length=6000)

    @field_validator('name')
    @classmethod
    def meaningful_name(cls, value):
        if not value.strip():
            raise ValueError('请输入项目名称')
        return value.strip()


class WorkspacePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    goal: str | None = Field(default=None, max_length=6000)
    archived: bool | None = None

    @field_validator('name')
    @classmethod
    def meaningful_name(cls, value):
        if value is not None and not value.strip():
            raise ValueError('请输入项目名称')
        return value.strip() if value else value


@router.get('/workspaces')
def list_workspaces(request: Request):
    return request.app.state.workspaces.list()


@router.post('/workspaces', status_code=201)
def create_workspace(body: WorkspaceIn, request: Request):
    return request.app.state.workspaces.create(body.name, body.goal)


@router.get('/workspaces/activity')
def activity(request: Request):
    from app.workspaces.activity import list_activity
    return list_activity(request.app.state.workspaces)


@router.patch('/workspaces/{workspace_id}')
def update_workspace(workspace_id: str, body: WorkspacePatch, request: Request):
    try:
        return request.app.state.workspaces.update(workspace_id, body.model_dump(exclude_none=True))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


class PaperCopyIn(BaseModel):
    model_config = {'extra': 'forbid'}
    target_workspace: str = Field(pattern=r'^(legacy|[a-f0-9]{32})$')
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    include_notes: bool = False


@router.post('/papers/{paper_id}/copy-to-workspace', status_code=201)
def copy_to_workspace(paper_id: int, body: PaperCopyIn, request: Request):
    from app.workspaces.copying import copy_paper, CopyConflict
    try:
        return copy_paper(request.app.state.workspaces, current_workspace.get(),
                          body.target_workspace, paper_id, body.request_id, body.include_notes)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except CopyConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except OSError as exc:
        import logging
        logging.getLogger(__name__).exception('Paper copy file operation failed')
        raise HTTPException(503, '复制文件未完成，请检查磁盘空间与文件权限后重试。') from exc
