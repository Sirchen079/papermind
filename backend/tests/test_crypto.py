from app.security.crypto import Crypto
from app.security.master_key import load_or_create_master_key


def test_master_key_is_stable(tmp_path):
    p = tmp_path / "mk"
    k1 = load_or_create_master_key(p)
    k2 = load_or_create_master_key(p)
    assert k1 == k2
    assert p.exists()


def test_encrypt_decrypt_roundtrip(tmp_path):
    key = load_or_create_master_key(tmp_path / "mk")
    c = Crypto(key)
    token = c.encrypt("sk-secret-123")
    assert token != "sk-secret-123"
    assert c.decrypt(token) == "sk-secret-123"


def test_distinct_keys_yield_distinct_ciphertext(tmp_path):
    a = Crypto(load_or_create_master_key(tmp_path / "a"))
    b = Crypto(load_or_create_master_key(tmp_path / "b"))
    assert a.encrypt("x") != b.encrypt("x")
