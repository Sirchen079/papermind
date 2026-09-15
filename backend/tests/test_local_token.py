"""P16 本地 token：高危端点的启动时本地凭证。

三部分：
1. ``get_or_create_token``——数据目录 ``api_token`` 文件的读/建。
2. ``require_local_token``——FastAPI 依赖（X-Local-Token 头校验）。
3. ``inject_local_token``——把 token 以 meta 标签注入 index.html。
"""

import os

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app import paths


# ---------------------------------------------------------------------------
# fixtures：对齐 conftest 的做法——用 PAPERMIND_DATA_DIR 指向 tmp_path。
# ---------------------------------------------------------------------------


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    data = tmp_path / "data"
    # exist_ok: 与 conftest 的 env fixture（client 依赖）共享同一数据目录。
    data.mkdir(exist_ok=True)
    monkeypatch.setenv("PAPERMIND_DATA_DIR", str(data))
    return data


@pytest.fixture
def local_token(data_dir):
    from app.security import local_token

    local_token.reset_token_cache()
    yield local_token
    local_token.reset_token_cache()


def _protected_app() -> FastAPI:
    from app.security.local_token import require_local_token

    app = FastAPI()

    @app.get("/protected")
    def protected(_: str = Depends(require_local_token)) -> dict:
        return {"ok": True}

    return app


# ---------------------------------------------------------------------------
# get_or_create_token
# ---------------------------------------------------------------------------


def test_token_created_in_data_dir(data_dir, local_token):
    token = local_token.get_or_create_token()
    assert token
    path = data_dir / "api_token"
    assert path.is_file()
    assert path.read_text(encoding="utf-8").strip() == token


def test_token_is_stable_across_calls(data_dir, local_token):
    first = local_token.get_or_create_token()
    assert local_token.get_or_create_token() == first


def test_existing_file_is_read_and_stripped(data_dir, local_token):
    (data_dir / "api_token").write_text("  preset-token\n", encoding="utf-8")
    assert local_token.get_or_create_token() == "preset-token"


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only file mode")
def test_token_file_mode_0600_on_posix(data_dir, local_token):
    local_token.get_or_create_token()
    mode = (data_dir / "api_token").stat().st_mode & 0o777
    assert mode == 0o600


def test_token_has_sufficient_entropy(data_dir, local_token):
    # token_urlsafe(32) -> 43 个 base64url 字符。
    assert len(local_token.get_or_create_token()) >= 40


def test_empty_token_file_is_regenerated(data_dir, local_token):
    # 安全复审 BLOCKING：strip 后为空的 api_token 文件不可信，必须重新生成并覆写。
    path = data_dir / "api_token"
    path.write_text("   \n", encoding="utf-8")
    token = local_token.get_or_create_token()
    assert token
    assert path.read_text(encoding="utf-8").strip() == token
    assert local_token.get_or_create_token() == token


# ---------------------------------------------------------------------------
# require_local_token 依赖
# ---------------------------------------------------------------------------


def test_correct_header_passes(local_token):
    token = local_token.get_or_create_token()
    resp = TestClient(_protected_app()).get(
        "/protected", headers={"X-Local-Token": token}
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_wrong_header_403(local_token):
    local_token.get_or_create_token()
    resp = TestClient(_protected_app()).get(
        "/protected", headers={"X-Local-Token": "wrong-token"}
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "local token required"


def test_missing_header_403(local_token):
    local_token.get_or_create_token()
    resp = TestClient(_protected_app()).get("/protected")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "local token required"


def test_dependency_tracks_reset_cache(local_token):
    # reset 钩子后重新从（已变化的）数据目录解析 token。
    from app.security import local_token as lt

    first = lt.get_or_create_token()
    resp = TestClient(_protected_app()).get(
        "/protected", headers={"X-Local-Token": first}
    )
    assert resp.status_code == 200
    lt.reset_token_cache()
    resp = TestClient(_protected_app()).get(
        "/protected", headers={"X-Local-Token": first}
    )
    assert resp.status_code == 200


def test_empty_token_dependency_fails_closed_403(data_dir, local_token):
    # 安全复审 BLOCKING：当前 token 为空时依赖必须直接 403（fail-closed）——
    # 空 X-Local-Token 头绝不能与空 token compare_digest 匹配通过。
    from app.security import local_token as lt

    lt.get_or_create_token()  # 先生成，再人为清空文件模拟空 token 状态。
    (data_dir / "api_token").write_text("", encoding="utf-8")
    lt.reset_token_cache()

    resp = TestClient(_protected_app()).get(
        "/protected", headers={"X-Local-Token": ""}
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "local token required"


# ---------------------------------------------------------------------------
# inject_local_token（纯函数）
# ---------------------------------------------------------------------------


def test_inject_before_first_head_close():
    from app.main import inject_local_token

    page = "<html><head><title>t</title></head><body></body></html>"
    out = inject_local_token(page, "tok-123")
    assert out == (
        "<html><head><title>t</title>"
        '<meta name="papermind-local-token" content="tok-123">'
        "</head><body></body></html>"
    )


def test_inject_only_once_with_multiple_heads():
    from app.main import inject_local_token

    page = "<html><head></head></head><body></body></html>"
    out = inject_local_token(page, "t")
    assert out.count("<meta ") == 1
    assert out.index("<meta ") < out.index("</head>")


def test_no_head_returns_unchanged():
    from app.main import inject_local_token

    page = "<html><body>hi</body></html>"
    assert inject_local_token(page, "tok") is page


def test_inject_escapes_token():
    from app.main import inject_local_token

    out = inject_local_token("<html><head></head></html>", 'a"b<c>&d')
    assert 'content="a&quot;b&lt;c&gt;&amp;d"' in out


# ---------------------------------------------------------------------------
# API：GET "/" 注入 token（仅当 dist/index.html 存在）
# ---------------------------------------------------------------------------


def test_root_serves_index_with_token(client, local_token):
    if not (paths.frontend_dist() / "index.html").is_file():
        pytest.skip("frontend/dist/index.html not built")
    token = local_token.get_or_create_token()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert '<meta name="papermind-local-token"' in resp.text
    assert token in resp.text


def test_root_still_served_via_trusted_host_client(client, local_token):
    # 与 TrustedHostMiddleware 共存：默认 testserver Host 下 "/" 可用。
    if not (paths.frontend_dist() / "index.html").is_file():
        pytest.skip("frontend/dist/index.html not built")
    resp = client.get("/")
    assert resp.status_code == 200
