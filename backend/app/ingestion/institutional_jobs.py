"""Durable workspace jobs around one isolated, visible institution browser."""
from contextvars import copy_context
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from threading import Event, Thread
import time
from uuid import uuid4

from fastapi import HTTPException
from sqlmodel import Session
from app.config import get_settings
from app.ingestion import institutional as access, institutional_runtime as runtime
from app.ingestion.institutional_worker import SOURCE
from app.models import Paper

_active = {}
_finished = {'attached', 'has_pdf'}
_statuses = {'waiting_user', 'verification_required', 'no_permission', 'needs_attention', 'needs_manual', 'unverified'}


def _path(job_id):
    if not re.fullmatch('[a-f0-9]{32}', job_id):
        raise HTTPException(404, '下载任务不存在。')
    return Path(get_settings().data_dir) / 'institutional-jobs' / (job_id + '.json')


def get_job(job_id):
    path = _path(job_id)
    if not path.is_file():
        raise HTTPException(404, '下载任务不存在。')
    with access._json_lock:
        job = json.loads(path.read_text(encoding='utf-8'))
    if job['status'] == 'running' and str(path) not in _active:
        job.update(status='interrupted', phase='interrupted')
        access.write_json(path, job)
    return job


def list_jobs():
    folder = _path('0' * 32).parent
    return [get_job(p.stem) for p in sorted(folder.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:20]]


def cancel(job_id):
    job = get_job(job_id)
    event = _active.get(str(_path(job_id)))
    if event:
        event.set()
    return job


def start(session, paper_ids, mode='auto'):
    if not runtime.ready():
        raise HTTPException(409, '请先在设置 → 图书馆下载环境完成安装，再使用图书馆渠道获取。')
    preferences = access.config()
    if not preferences['institution']:
        raise HTTPException(422, '请先配置学校或机构。')
    if not access._browser_lock.acquire(blocking=False):
        raise HTTPException(409, '机构浏览器正在处理任务，请等待完成或停止当前任务。')
    path = _path(uuid4().hex)
    event = Event()
    job = dict(id=path.stem, status='running', phase='preparing', mode=mode, current_paper_id=None,
               updated_at=datetime.now(timezone.utc).isoformat(),
               results=[], error='')
    records = []
    for pid in dict.fromkeys(paper_ids):
        paper = session.get(Paper, pid)
        status = 'not_found' if paper is None or paper.is_deleted else 'has_pdf' if paper.pdf_path else 'pending'
        job['results'].append({'paper_id': pid, 'title': paper.title if paper else '', 'doi': paper.doi if paper else '', 'status': status})
        if status == 'pending':
            records.append({'paper_id': pid, 'title': paper.title, 'doi': paper.doi})
    _active[str(path)] = event
    try:
        access.write_json(path, job)
        context = copy_context()
        Thread(target=context.run, args=(_work, session.get_bind(), path, job, records, preferences, event), daemon=True).start()
    except Exception:
        _active.pop(str(path), None)
        access._browser_lock.release()
        raise
    return job


def _terminate(process):
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], shell=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=10)
    else:
        process.kill()
    process.wait(timeout=10)


def _work(engine, path, job, records, preferences, event):
    process = None
    failure_status = 'environment_failed'
    def save(phase=None):
        job['updated_at'] = datetime.now(timezone.utc).isoformat()
        if phase:
            job['phase'] = phase
        access.write_json(path, job)
    def collect(folder):
        for expected in records:
            result = next(x for x in job['results'] if x['paper_id'] == expected['paper_id'])
            result_path = folder / (str(expected['paper_id']) + '.json')
            if result['status'] != 'pending' or not result_path.is_file():
                continue
            item = json.loads(result_path.read_text(encoding='utf-8'))
            if item.get('status') == 'success':
                try:
                    with Session(engine) as session:
                        result['status'] = access.attach(session, expected['paper_id'], item, folder, expected)
                except Exception:
                    result['status'] = 'import_failed'
            else:
                result['status'] = item.get('status') if item.get('status') in _statuses else 'needs_attention'
            save()
    try:
        if records:
            if not runtime.ready():
                raise runtime.PreparationError('下载环境已不可用，请在设置中检查并重新安装。')
            if event.is_set():
                return
            job['error'] = ''
            failure_status = 'worker_failed'
            runtime.root().mkdir(parents=True, exist_ok=True)
            from app.archive.application import _backup_lock
            with _backup_lock(runtime.root() / 'browser.lock', '机构浏览器正在被另一个窗口使用。'):
                folder = runtime.root() / 'runs' / job['id']
                access.write_json(folder / 'request.json', {**preferences, 'papers': records, 'mode': job['mode']})
                process = subprocess.Popen([str(runtime.python_path()), '-c', SOURCE, str(folder)],
                    env=runtime.environment(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, shell=False,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                save('downloading')
                deadline = time.monotonic() + 1500 * len(records)
                while process.poll() is None:
                    collect(folder)
                    if all(row['status'] in _finished for row in job['results']):
                        _terminate(process)
                        break
                    if event.is_set() or time.monotonic() > deadline:
                        (folder / 'cancel').touch()
                        _terminate(process)
                        break
                    progress = folder / 'progress.json'
                    if progress.is_file():
                        data = json.loads(progress.read_text(encoding='utf-8'))
                        if data.get('phase') in {'downloading', 'waiting_user', 'waiting_login', 'waiting_verification'}:
                            job['current_paper_id'] = data.get('paper_id')
                            save(data['phase'])
                    event.wait(.5)
                collect(folder)
                if any(x['status'] == 'pending' for x in job['results']):
                    job['error'] = '下载引擎退出且未返回结果，可使用常用浏览器下载后上传 PDF。'
    except runtime.PreparationError as exc:
        job['error'] = str(exc)
    except Exception:
        job['error'] = ('下载环境尚未准备完成' if failure_status == 'environment_failed' else '机构下载引擎未能运行') + '；可重试或使用常用浏览器下载后上传 PDF。'
    finally:
        if process is not None:
            try:
                _terminate(process)
            except Exception:
                pass
        for result in job['results']:
            if result['status'] == 'pending':
                result['status'] = 'stopped' if event.is_set() else failure_status
        job['status'] = 'stopped' if event.is_set() else 'completed' if all(
            x['status'] in _finished for x in job['results']) else 'needs_attention'
        try:
            save('done')
        finally:
            _active.pop(str(path), None)
            access._browser_lock.release()


def attach_uploaded(session, job_id, paper_id, data):
    """Recovery does not depend on downloading or launching the isolated engine."""
    with access._json_lock:
        return _attach_uploaded(session, job_id, paper_id, data)


def _attach_uploaded(session, job_id, paper_id, data):
    from tempfile import TemporaryDirectory
    job = get_job(job_id)
    if job['status'] == 'running':
        raise HTTPException(409, '请先停止当前任务再上传 PDF。')
    result = next((r for r in job['results'] if r['paper_id'] == paper_id), None)
    paper = session.get(Paper, paper_id)
    if result is None or paper is None or paper.is_deleted:
        raise HTTPException(404, '该任务中没有这篇论文。')
    with TemporaryDirectory(prefix='upload-', dir=_path(job_id).parent) as temporary:
        folder = Path(temporary)
        pdf = folder / 'paper.pdf'
        pdf.write_bytes(data)
        item = dict(status='success', verified_match=True, doi=paper.doi, pdf_path=str(pdf))
        try:
            status = access.attach(session, paper_id, item, folder,
                {'doi': result.get('doi', paper.doi), 'title': result.get('title') or paper.title}, access_mode='manual_pdf_upload')
        except (ValueError, RuntimeError):
            raise HTTPException(422, 'PDF 无法解析，请确认下载的是完整正文。') from None
    if status not in _finished:
        raise HTTPException(422, 'PDF 未通过正文格式或论文身份校验，请确认下载的是本篇正文。')
    result['status'] = status
    job['updated_at'] = datetime.now(timezone.utc).isoformat()
    if all(r['status'] in _finished for r in job['results']):
        job.update(status='completed', phase='done', error='')
    access.write_json(_path(job_id), job)
    return job
