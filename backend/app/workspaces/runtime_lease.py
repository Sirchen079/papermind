"""Application lifetime read lease, mutually exclusive with offline restore."""
import os
from pathlib import Path


class RuntimeLease:
    def __init__(self, root: Path, *, exclusive: bool = False):
        root.mkdir(parents=True, exist_ok=True)
        self.file = None
        path = root / '.runtime-use.lock'
        if os.name == 'nt':
            import ctypes
            import msvcrt
            from ctypes import wintypes
            create = ctypes.WinDLL('kernel32', use_last_error=True).CreateFileW
            create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            create.restype = wintypes.HANDLE
            # Multiple servers may read the same application. Restore opens
            # this path with ReadWrite + FileShare.None, excluding all readers.
            handle = create(str(path), 0xC0000000 if exclusive else 0x80000000,
                            0 if exclusive else 1, None, 4, 0x80, None)
            if handle == wintypes.HANDLE(-1).value:
                raise OSError('数据目录正在恢复或暂时无法访问，请完成恢复后再启动 PaperMind。')
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
            self.file = os.fdopen(fd, 'rb')
        else:
            import fcntl
            self.file = path.open('a+b')
            try:
                fcntl.flock(self.file.fileno(), (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            except OSError:
                self.close()
                raise

    def close(self):
        if self.file is not None:
            self.file.close()
            self.file = None
