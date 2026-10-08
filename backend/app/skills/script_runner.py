"""Run an installed skill's original script using the desktop's Python runtime."""
import json
import subprocess
import sys
import time
from pathlib import Path

from app.skills.sandbox import _sandbox_env
from app.skills import worker


def run_bundled_script(script: Path, args: list[str], work: Path, timeout=180) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    job = work / 'job.json'
    job.write_text(json.dumps({'script': str(script.resolve()), 'args': args}), encoding='utf-8')
    command = ([sys.executable, '--run-bundled-skill', str(job)] if getattr(sys, 'frozen', False)
               else [sys.executable, str(Path(worker.__file__).resolve()), str(job)])
    start = time.monotonic()
    code, error = -1, None
    try:
        proc = subprocess.run(command, cwd=work, env=_sandbox_env({'PYTHONIOENCODING': 'utf-8'}),
            capture_output=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        code = proc.returncode
        if not (work / 'stdout.txt').exists():
            error = '技能进程没有产生执行记录：' + proc.stderr.decode('utf-8', errors='replace')[:2000]
    except subprocess.TimeoutExpired:
        error = f'技能运行超过 {timeout} 秒，本次执行已停止；已有资料和草稿仍可继续使用。'
    except OSError as exc:
        error = str(exc)
    def log(name):
        path = work / name
        return path.read_text(encoding='utf-8', errors='replace')[-12000:] if path.exists() else ''
    return {'exit_code': code, 'duration_ms': round((time.monotonic()-start)*1000),
            'stdout': log('stdout.txt'), 'stderr': error or log('stderr.txt'), 'process_error': error}
