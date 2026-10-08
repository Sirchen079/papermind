"""Application-owned GGUF models and CPU inference, independent of project databases."""
import atexit
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import threading
import time
from uuid import uuid4

import httpx
from app import paths
from app.providers.runtime_job import RuntimeJob

PREFIX = 'http://127.0.0.1/papermind-managed/'


def model_id(base_url):
    match = re.fullmatch(re.escape(PREFIX)+r'([a-f0-9]{32})', base_url or '')
    return match.group(1) if match else None


def engine_path():
    override = os.environ.get('PAPERMIND_LLAMA_SERVER')
    if override:
        return Path(override).resolve()
    base = paths._meipass() / 'local_runtime' if paths.is_frozen() else paths.exe_dir() / 'build/vendor/llama_cpp'
    return base / ('llama-server.exe' if os.name == 'nt' else 'llama-server')


@dataclass
class Running:
    process: subprocess.Popen
    port: int
    key: str
    log: Path
    state: str = 'starting'
    error: str = ''
    done: threading.Event = field(default_factory=threading.Event)


class Manager:
    def __init__(self, application_dir):
        self.root = Path(application_dir).resolve() / 'local_ai'
        self.lock = threading.RLock()
        self.running = {}
        self.job = None
        self.closed = False

    def catalog(self):
        path = self.root / 'catalog.json'
        if not path.exists():
            return []
        rows = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(rows, list):
            raise ValueError('本地模型目录损坏，请保留文件后恢复备份。')
        return rows

    def _save(self, rows):
        self.root.mkdir(parents=True, exist_ok=True)
        temp = self.root / (uuid4().hex+'.tmp')
        temp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(self.root/'catalog.json')

    def _get(self, mid):
        row = next((r for r in self.catalog() if r['id'] == mid), None)
        if row is None:
            raise LookupError('本地模型不存在，请重新导入模型文件。')
        return row

    def _weight(self, row):
        # Paths are relative to the application store so portable copies still work.
        if not re.fullmatch(r'[a-f0-9]{64}', row['sha256']):
            raise ValueError('模型文件记录无效。')
        return self.root/'weights'/(row['sha256']+'.gguf')

    def import_stream(self, stream, name, kind, context_window):
        if kind not in {'chat', 'embedding'} or context_window < 1:
            raise ValueError('请选择模型用途并填写有效上下文长度。')
        directory = self.root/'weights'; directory.mkdir(parents=True, exist_ok=True)
        temporary = directory/(uuid4().hex+'.part')
        try:
            digest = hashlib.sha256(); size = 0
            with temporary.open('wb') as output:
                first = stream.read(4)
                if first != b'GGUF':
                    raise ValueError('请选择 GGUF 格式的模型文件。')
                output.write(first); digest.update(first); size += len(first)
                while chunk := stream.read(4*1024*1024):
                    output.write(chunk); digest.update(chunk); size += len(chunk)
            sha = digest.hexdigest()
            with self.lock:
                rows = self.catalog()
                existing = next((r for r in rows if r['sha256'] == sha and r['kind'] == kind and r['context_window'] == context_window), None)
                target = directory/(sha+'.gguf')
                if not target.exists(): temporary.replace(target)
                if existing: return self._public(existing)
                row = {'id':uuid4().hex, 'name':name.strip() or 'GGUF 模型', 'kind':kind,
                    'context_window':context_window, 'sha256':sha, 'bytes':size}
                rows.append(row); self._save(rows)
                return self._public(row)
        finally:
            temporary.unlink(missing_ok=True)

    def _public(self, row):
        run = self.running.get(row['id'])
        if run and run.process.poll() is not None and run.state not in {'stopped', 'error'}:
            run.state = 'error'; run.error = '模型服务已退出，可重新启动。'; run.done.set()
        return {**row, 'state':run.state if run else 'stopped', 'error':run.error if run else '',
            'available':self._weight(row).is_file()}

    def status(self):
        with self.lock:
            return {'engine_available':engine_path().is_file(), 'engine_version':'llama.cpp b11146 CPU',
                'models':[self._public(row) for row in self.catalog()]}

    def start(self, mid):
        with self.lock:
            if self.closed: raise ValueError('应用正在退出。')
            row = self._get(mid); current = self.running.get(mid)
            if current and current.state in {'starting','ready'} and current.process.poll() is None:
                return self._public(row)
            if current and current.process.poll() is None:self.stop(mid)
            executable = engine_path(); weight = self._weight(row)
            if not executable.is_file(): raise ValueError('本地推理引擎缺失，请重新安装包含本地引擎的版本。')
            if not weight.is_file(): raise ValueError('模型文件缺失，请重新导入。')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0)); port = sock.getsockname()[1]
            key = secrets.token_urlsafe(24)
            logs = self.root/'logs'; logs.mkdir(parents=True, exist_ok=True)
            logfile = logs/(mid+'.log')
            args = [str(executable), '-m', str(weight), '--host','127.0.0.1','--port',str(port),
                '--alias','pm-'+mid,'--api-key',key,'--ctx-size',str(row['context_window']),
                '--threads',str(max(1,min(8,(os.cpu_count() or 2)//2))), '--parallel','1','--n-gpu-layers','0']
            if row['kind'] == 'embedding': args += ['--embedding','--pooling','mean']
            else: args += ['--chat-template-kwargs','{"enable_thinking":false}']
            if self.job is None: self.job = RuntimeJob()
            with logfile.open('wb') as log:
                process = subprocess.Popen(args, cwd=executable.parent, stdout=log, stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            try: self.job.assign(process)
            except Exception:
                process.terminate(); process.wait(timeout=10); raise
            run = Running(process,port,key,logfile); self.running[mid] = run
            threading.Thread(target=self._watch,args=(mid,run),daemon=True,name='local-model-start').start()
            return self._public(row)

    def _watch(self, mid, run):
        try:
            with httpx.Client(trust_env=False, timeout=1) as client:
                deadline = time.monotonic()+180
                while not run.done.wait(.2):
                    if run.process.poll() is not None:
                        raise RuntimeError('模型未能加载。请检查文件是否完整、模型类型是否匹配，以及内存是否足够。')
                    if time.monotonic()>deadline: raise RuntimeError('模型加载超时，可降低上下文长度或使用较小模型后重试。')
                    try:
                        response=client.get(f'http://127.0.0.1:{run.port}/v1/models',headers={'Authorization':'Bearer '+run.key})
                        if response.status_code!=200: continue
                        names={m.get('id') for m in response.json().get('data',[])}
                        if 'pm-'+mid not in names: continue
                    except (httpx.HTTPError,ValueError): continue
                    with self.lock:
                        if not run.done.is_set(): run.state='ready'; run.done.set()
                    return
        except Exception as exc:
            with self.lock:
                if not run.done.is_set():
                    run.state='error'; run.error=str(exc); run.done.set()
                    if run.process.poll() is None: run.process.terminate()

    def ready(self, mid):
        self.start(mid)
        with self.lock: run=self.running[mid]
        if not run.done.wait(185): raise ValueError('模型仍在加载，请稍后重试。')
        with self.lock:
            if run.state!='ready' or run.process.poll() is not None:
                raise ValueError(run.error or '模型已停止。')
            return f'http://127.0.0.1:{run.port}/v1',run.key

    def stop(self, mid):
        with self.lock:
            row=self._get(mid); run=self.running.get(mid)
            if run:
                run.state='stopped';run.error='';run.done.set()
                if run.process.poll() is None:
                    run.process.terminate()
                    try: run.process.wait(timeout=8)
                    except subprocess.TimeoutExpired: run.process.kill();run.process.wait(timeout=5)
            return self._public(row)

    def remove(self, mid):
        with self.lock:
            row=self._get(mid);self.stop(mid)
            remaining=[r for r in self.catalog() if r['id']!=mid]
            self._save(remaining)
            if not any(r['sha256']==row['sha256'] for r in remaining):self._weight(row).unlink(missing_ok=True)
            self.running.pop(mid,None)

    def close(self):
        with self.lock:
            self.closed=True
            try:
                for run in self.running.values():
                    run.state='stopped';run.done.set()
                    if run.process.poll() is None:
                        run.process.terminate()
                        try:run.process.wait(timeout=8)
                        except subprocess.TimeoutExpired:run.process.kill();run.process.wait(timeout=5)
            finally:
                if self.job:self.job.close()


_managers={}
_lock=threading.Lock()


def manager(application_dir=None):
    if application_dir is None:
        from app.providers.shared import application_dir as current_dir
        application_dir=current_dir()
    root=Path(application_dir).resolve()
    with _lock:
        if root not in _managers or _managers[root].closed:
            _managers[root]=Manager(root)
        return _managers[root]


def close_all():
    for instance in list(_managers.values()):instance.close()


atexit.register(close_all)
