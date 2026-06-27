from pathlib import Path

from cryptography.fernet import Fernet


def load_or_create_master_key(path: Path) -> bytes:
    """Return the Fernet master key at ``path``, generating it on first use.

    The key file must live outside version control (it protects API keys at
    rest). Callers pass the resolved path from settings.
    """
    path = Path(path)
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    path.write_bytes(key)
    return key
