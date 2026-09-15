"""Windows desktop host: native window, private backend, one instance per library."""
from __future__ import annotations

import ctypes
import html
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import sys
import threading
import time

from app.paths import default_data_dir, exe_dir, is_frozen

TITLE = "PaperMind"
DEFAULT_PORT = 4278


def activate_process(pid: int) -> None:
    """Bring the existing instance forward without starting another backend."""
    if sys.platform != "win32" or not pid:
        return
    from ctypes import wintypes
    user32 = ctypes.windll.user32

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
            return False
        return True

    user32.EnumWindows(visit, 0)


class InstanceLock:
    def __init__(self, path: Path):
        self.path = path
        self.file = None

    def acquire(self) -> bool:
        import msvcrt
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.file.seek(1)
            try:
                activate_process(int(self.file.read().decode("ascii")))
            except (ValueError, OSError):
                pass
            self.file.close()
            self.file = None
            return False
        self.file.seek(1)
        self.file.truncate()
        self.file.write(str(os.getpid()).encode("ascii"))
        self.file.flush()
        return True

    def close(self):
        if self.file is not None:
            import msvcrt
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            self.file.close()
            self.file = None


def reserve_socket(port: int = DEFAULT_PORT, *, fallback: bool = True) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Reserve the port ourselves; never load an arbitrary pre-existing service.
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            if not fallback:
                raise
            sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        return sock
    except BaseException:
        sock.close()
        raise


class LocalBackend:
    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        self.cancelled = threading.Event()
        self.failure: BaseException | None = None
        self.server = None
        self.thread = threading.Thread(target=self._run, name="papermind-service", daemon=True)

    def _run(self):
        try:
            import uvicorn
            from app.main import create_app
            app = create_app()
            if self.cancelled.is_set():
                return
            self.server = uvicorn.Server(uvicorn.Config(
                app, log_config=None, log_level="warning", access_log=False,
                timeout_graceful_shutdown=5,
            ))
            if self.cancelled.is_set():
                return
            self.server.run(sockets=[self.sock])
        except BaseException as error:
            self.failure = error
            logging.exception("Desktop backend failed")

    def start(self):
        self.thread.start()

    def wait_ready(self, timeout: float = 90) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.cancelled.is_set():
            if self.failure:
                raise RuntimeError("本地服务启动失败，请查看日志。") from self.failure
            if self.server and self.server.started:
                return True
            if not self.thread.is_alive():
                raise RuntimeError("本地服务已退出，请重新启动 PaperMind。")
            self.cancelled.wait(.05)
        if self.cancelled.is_set():
            return False
        raise TimeoutError("初始化超时，请关闭窗口后重试。")

    def stop(self):
        self.cancelled.set()
        if self.server:
            self.server.should_exit = True
        if self.thread.ident is not None:
            self.thread.join(timeout=10)
        self.sock.close()


def loading_page(message="正在打开你的研究空间…", *, error=False) -> str:
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
    <style>body{{margin:0;background:#f8faff;color:#1d2942;font:16px 'Microsoft YaHei',sans-serif;display:grid;place-content:center;height:100vh;text-align:center}}h1{{font-size:32px;letter-spacing:-1px;margin:0 0 16px}}p{{color:#63718b;max-width:680px;line-height:1.8;padding:0 28px}}.dot{{width:12px;height:12px;border-radius:50%;background:#316be4;margin:0 auto 24px;animation:pulse 1s alternate infinite}}@keyframes pulse{{to{{opacity:.3}}}}</style>
    {'' if error else '<div class="dot"></div>'}<h1>PaperMind</h1><p>{html.escape(message)}</p></html>"""


def configure_desktop_logs(profile: Path) -> Path:
    profile.mkdir(parents=True, exist_ok=True)
    log_file = profile / "desktop.log"
    handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    # Windowed PyInstaller provides no stdout/stderr. Some dependencies print.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    return log_file


def main() -> None:
    profile = default_data_dir().resolve() / "desktop"
    log_file = configure_desktop_logs(profile)
    lock = InstanceLock(profile / "instance.lock")
    if not lock.acquire():
        return
    backend = None
    try:
        import webview
        runtime = (Path(sys._MEIPASS) / "desktop" if is_frozen() else exe_dir() / "build" / "vendor") / "webview2"
        if (runtime / "msedgewebview2.exe").is_file():
            webview.settings["WEBVIEW2_RUNTIME_PATH"] = str(runtime)
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.settings["ALLOW_FILE_URLS"] = False
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
        # Opt-in development inspection. Disabled in ordinary installed runs.
        if os.environ.get("PAPERMIND_DESKTOP_DEBUG_PORT"):
            webview.settings["REMOTE_DEBUGGING_PORT"] = int(os.environ["PAPERMIND_DESKTOP_DEBUG_PORT"])
        port = int(os.environ.get("PAPERMIND_PORT", DEFAULT_PORT))
        backend = LocalBackend(reserve_socket(port, fallback="PAPERMIND_PORT" not in os.environ))
        state_path = profile / "window.json"
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        width = max(880, min(1800, int(state.get("width", 1280))))
        height = max(620, min(1200, int(state.get("height", 850))))
        window = webview.create_window(
            TITLE, html=loading_page(), width=width, height=height,
            min_size=(880, 620), text_select=True, zoomable=True,
            background_color="#F8FAFF",
        )

        def on_close():
            backend.cancelled.set()
            try:
                state_path.write_text(json.dumps({"width":window.width,"height":window.height}), encoding="utf-8")
            except OSError:
                logging.exception("Could not save window size")

        def boot():
            backend.start()
            try:
                if backend.wait_ready():
                    (profile / "session.json").write_text(json.dumps({"pid":os.getpid(),"url":backend.url}), encoding="utf-8")
                    window.load_url(backend.url)
            except Exception:
                logging.exception("Desktop initialization failed")
                if not backend.cancelled.is_set():
                    window.load_html(loading_page(f"打开失败。请关闭后重试；详细日志：{log_file}", error=True))

        window.events.closed += on_close
        icon = (Path(sys._MEIPASS) / "desktop" if is_frozen() else exe_dir() / "build" / "assets") / "papermind.ico"
        webview.start(
            boot, gui="edgechromium", private_mode=False, storage_path=str(profile / "webview"),
            icon=str(icon), localization={"global.quit":"退出","global.cancel":"取消","global.ok":"确定","global.saveFile":"保存文件","windows.fileFilter.allFiles":"所有文件"},
        )
    except Exception:
        logging.exception("Desktop window failed")
        ctypes.windll.user32.MessageBoxW(None, f"PaperMind 无法启动。请确认已安装 Microsoft Edge WebView2 运行时。\n\n日志：{log_file}", TITLE, 0x10)
    finally:
        if backend:
            backend.stop()
        lock.close()
