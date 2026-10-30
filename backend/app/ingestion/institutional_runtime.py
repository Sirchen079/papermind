"""Isolated, revision-pinned institutional downloader; no changes to app Python."""
import hashlib
import io
import os
from pathlib import Path
import platform
import shutil
import subprocess
from threading import Lock
import zipfile

import httpx

REVISION = '7a233a4df767c7fe64f03491ef1b6abe84d08c34'
UV_URL = 'https://releases.astral.sh/github/uv/releases/download/0.12.20/uv-x86_64-pc-windows-msvc.zip'
UV_SHA256 = '95f9bc30fbb3574d276e28ac4a6de932d25153645853d13da8c21eec3bc88d06'
_install_lock = Lock()


class PreparationError(RuntimeError):
    """A safe actionable installation error; never contains raw process output."""


def root() -> Path:
    # Browser credentials stay outside paper/project backups.
    return Path(os.environ.get('PAPERMIND_INSTITUTION_RUNTIME') or
                Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'PaperMindInstitutional')


def python_path() -> Path:
    return root() / REVISION[:12] / 'env' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def ready() -> bool:
    return python_path().is_file() and (python_path().parents[2] / 'ready').is_file()


def environment() -> dict:
    env = os.environ.copy()
    env.update(PYTHONUTF8='1', PYTHONUNBUFFERED='1', UV_NO_PROGRESS='1',
               UV_PYTHON_INSTALL_DIR=str(root() / 'python'), UV_CACHE_DIR=str(root() / 'cache'),
               CLOAKBROWSER_CACHE_DIR=str(root() / 'browser'))
    # A frozen app's loader paths must not contaminate the independent Python.
    for key in ('PYTHONHOME', 'PYTHONPATH', '_PYI_APPLICATION_HOME_DIR', '_PYI_PARENT_PROCESS_LEVEL'):
        env.pop(key, None)
    return env


def _uv() -> str:
    installed = shutil.which('uv')
    if installed:
        return installed
    target = root() / 'tools' / 'uv.exe'
    if target.is_file():
        return str(target)
    if os.name != 'nt' or platform.machine().lower() not in {'amd64', 'x86_64'}:
        raise RuntimeError('请先安装 uv；自动准备目前支持 Windows x64。')
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        response = client.get(UV_URL)
        response.raise_for_status()
    if hashlib.sha256(response.content).hexdigest() != UV_SHA256:
        raise ValueError('运行环境下载校验失败，请重试。')
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        binary = next(name for name in archive.namelist() if Path(name).name == 'uv.exe')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(binary))
    return str(target)


def _run(argv):
    try:
        subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace',
                       shell=False, check=True, timeout=900, env=environment(),
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.CalledProcessError as exc:
        diagnostic = (exc.stderr or '').lower()
        if any(word in diagnostic for word in ('tls', 'ssl', 'certificate')):
            message = '下载环境的 HTTPS/TLS 连接失败；请检查网络代理与系统证书，或使用常用浏览器下载后上传 PDF。'
        else:
            message = '下载环境安装失败；请检查网络与可用磁盘空间，或使用常用浏览器下载后上传 PDF。'
        raise PreparationError(message) from None
    except subprocess.TimeoutExpired:
        raise PreparationError('下载环境准备超时，可重试或使用常用浏览器下载后上传 PDF。') from None


def prepare(progress=lambda message: None):
    if not _install_lock.acquire(blocking=False):
        raise RuntimeError('下载环境正在准备，请稍候。')
    try:
        if ready():
            return
        root().mkdir(parents=True, exist_ok=True)
        progress('正在准备独立 Python 环境…')
        uv = _uv()
        python = python_path()
        if not python.is_file():
            _run([uv, 'venv', '--python', '3.12', '--managed-python', str(python.parents[1])])
        progress('正在安装机构下载引擎…')
        _run([uv, 'pip', 'install', '--python', str(python),
              f'instsci @ https://github.com/Rimagination/instsci/archive/{REVISION}.zip',
              'cloakbrowser==0.3.31'])
        progress('正在准备浏览器，首次下载可能需要数分钟…')
        _run([str(python), '-c', 'from instsci.cloakbrowser_compat import prepare_cloakbrowser_runtime; '
              'prepare_cloakbrowser_runtime(); from cloakbrowser.download import ensure_binary; ensure_binary()'])
        (python.parents[2] / 'ready').write_text(REVISION, encoding='utf-8')
    finally:
        _install_lock.release()
