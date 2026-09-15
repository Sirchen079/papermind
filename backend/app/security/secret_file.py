"""Serialize first use and publish a complete secret before other callers read it."""
import os
from pathlib import Path
import tempfile


def read_or_create(path: Path, generate, usable=lambda value: True) -> bytes:
    path = Path(path)
    try:
        stored = path.read_bytes()
    except FileNotFoundError:
        pass
    else:
        if usable(stored):
            return stored
    path.parent.mkdir(parents=True, exist_ok=True)
    # Process-local caches alone do not serialize concurrent cache misses or
    # another PaperMind process starting against the same directory.
    with path.with_name(path.name + '.lock').open('a+b') as lease:
        if os.name == 'nt':
            import msvcrt
            lease.seek(0)
            msvcrt.locking(lease.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lease.fileno(), fcntl.LOCK_EX)
        if path.exists():
            stored = path.read_bytes()
            if usable(stored):
                return stored
        value = generate()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix='.pm-secret-', dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            temporary.replace(path)
            return value
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
