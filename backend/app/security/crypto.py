from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet


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

    return _build_crypto(str(get_settings().resolved_master_key_path))
