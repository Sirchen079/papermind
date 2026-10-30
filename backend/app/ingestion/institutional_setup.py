"""Explicit machine-wide environment installation, separate from paper jobs."""
import json
from threading import RLock, Thread

from fastapi import HTTPException
from app.archive.application import _backup_lock
from app.ingestion import institutional as access, institutional_runtime as runtime

_lock = RLock()
_active = set()


def _paths():
    root = runtime.root()
    root.mkdir(parents=True, exist_ok=True)
    return root / 'installation.json', root / 'installation.lock'


def status():
    with _lock:
        path, lease_path = _paths()
        try:
            state = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            state = dict(status='not_installed', message='尚未安装图书馆下载环境', error='')
        if state['status'] == 'installing' and str(path) not in _active:
            try:
                with _backup_lock(lease_path):
                    state.update(status='interrupted', message='上次安装未完成', error='上次安装已中断，请重新安装。')
                    access.write_json(path, state)
            except ValueError:
                pass  # Another application window still owns the installation.
        available = runtime.ready()
        if available and str(path) not in _active:
            state.update(status='ready', message='下载环境已就绪', error='')
        elif state['status'] == 'ready' and not available:
            state.update(status='not_installed', message='下载环境文件不完整，请重新安装。')
        return {**state, 'ready': available and state['status'] == 'ready'}


def start():
    with _lock:
        current = status()
        if current['ready']:
            return current
        path, lease_path = _paths()
        if str(path) in _active:
            raise HTTPException(409, '下载环境正在安装，请等待当前安装结束。')
        lease = _backup_lock(lease_path, '另一个窗口正在安装下载环境。')
        try:
            lease.__enter__()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        state = dict(status='installing', message='正在准备安装…', error='')
        _active.add(str(path))
        try:
            access.write_json(path, state)
            Thread(target=_install, args=(path, state, lease), daemon=True).start()
        except Exception:
            _active.discard(str(path)); lease.__exit__(None, None, None)
            raise
        return {**state, 'ready': False}


def _install(path, state, lease):
    def progress(message):
        with _lock:
            state['message'] = message
            access.write_json(path, state)
    try:
        runtime.prepare(progress)
        if not runtime.ready():
            raise runtime.PreparationError('环境检查未通过，请重新安装。')
        state.update(status='ready', message='下载环境已就绪', error='')
    except runtime.PreparationError as exc:
        state.update(status='failed', message='下载环境安装失败', error=str(exc))
    except Exception:
        state.update(status='failed', message='下载环境安装失败', error='环境安装失败，请检查网络和磁盘空间后重试。')
    finally:
        with _lock:
            try:
                access.write_json(path, state)
            finally:
                _active.discard(str(path)); lease.__exit__(None, None, None)
