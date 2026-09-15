from pathlib import Path

from cryptography.fernet import Fernet


def load_or_create_master_key(path: Path) -> bytes:
    """Return the Fernet master key at ``path``, generating it on first use.

    The key file must live outside version control (it protects API keys at
    rest). Callers pass the resolved path from settings.
    """
    from app.security.secret_file import read_or_create
    return read_or_create(Path(path), Fernet.generate_key)
