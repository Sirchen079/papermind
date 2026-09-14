from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet


class MissingKeyError(LookupError):
    pass


def require_recoverable_key(key_path: Path, database: Path, table: str) -> None:
    """A missing key beside encrypted data needs recovery, not first-use setup."""
    if key_path.is_file() or not database.is_file():
        return
    import sqlite3
    from contextlib import closing
    assert table in {'provider', 'connection'}
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            if db.execute(f'SELECT 1 FROM "{table}" WHERE api_key_encrypted IS NOT NULL LIMIT 1').fetchone():
                raise MissingKeyError('模型配置的加密密钥缺失，请从备份恢复密钥后重试。现有配置已保留。')


class Crypto:
    def __init__(self, key: bytes) -> None:
        self._f = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return self._f.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        return self._f.decrypt(token.encode("ascii")).decode("utf-8")


@lru_cache(maxsize=8)
def _build_crypto(master_key_path: str) -> Crypto:
    from app.security.master_key import load_or_create_master_key

    return Crypto(load_or_create_master_key(Path(master_key_path)))


def get_crypto() -> Crypto:
    """Build a Crypto from the resolved master-key path.

    Cached by path so repeated requests don't re-read the key file; tests that
    override PAPERMIND_MASTER_KEY_PATH get a distinct cache entry per path.
    """
    from app.config import get_settings

    settings = get_settings()
    key = Path(settings.resolved_master_key_path)
    require_recoverable_key(key, Path(settings.resolved_db_path), 'provider')
    return _build_crypto(str(key))
