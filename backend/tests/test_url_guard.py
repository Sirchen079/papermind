import secrets

import httpx
import pytest

from app.ingestion.sources import fetch_arxiv
from app.security.url_guard import (
    ensure_arxiv_url,
    ensure_http_url,
    validated_get,
)


# Runtime-generated placeholder; avoids hardcoding credential-like literals.
FAKE_KEY = "test-" + secrets.token_hex(16)


# --- ensure_http_url (pure function, no network) ---


def test_accepts_https_url():
    url = "https://api.deepseek.com/v1"
    assert ensure_http_url(url) == url


def test_accepts_http_url():
    url = "http://api.example.com:8000/v1"
    assert ensure_http_url(url) == url


@pytest.mark.parametrize("url", ["ftp://example.com/files", "file:///etc/passwd"])
def test_rejects_non_http_schemes(url):
    with pytest.raises(ValueError) as excinfo:
        ensure_http_url(url)
    assert url.split("://")[0] in str(excinfo.value)


def test_rejects_empty_scheme():
    with pytest.raises(ValueError):
        ensure_http_url("example.com/v1")


def test_rejects_missing_host():
    with pytest.raises(ValueError) as excinfo:
        ensure_http_url("http://")
    assert "http" in str(excinfo.value)


@pytest.mark.parametrize("url", ["http://localhost:11434/v1", "http://127.0.0.1:11434/v1"])
def test_allows_local_hosts(url):
    # Local Ollama / LM Studio endpoints are a legitimate scenario; no
    # private-network blocking by design.
    assert ensure_http_url(url) == url


# --- ensure_arxiv_url (pure function, no network) ---


@pytest.mark.parametrize(
    "url",
    [
        "https://arxiv.org/pdf/1",
        "https://export.arxiv.org/pdf/1",
        "http://arxiv.org",
        "https://ARXIV.ORG/pdf/1",
    ],
)
def test_arxiv_url_accepts_arxiv_hosts(url):
    assert ensure_arxiv_url(url) == url


@pytest.mark.parametrize(
    "url, host",
    [
        ("https://evil.com/pdf", "evil.com"),
        ("https://arxiv.org.evil.com/pdf", "arxiv.org.evil.com"),
        ("ftp://arxiv.org/pdf", "arxiv.org"),
    ],
)
def test_arxiv_url_rejects_non_arxiv_targets(url, host):
    with pytest.raises(ValueError) as excinfo:
        ensure_arxiv_url(url)
    assert host in str(excinfo.value)


# --- API wiring (uses the shared client fixture from conftest.py) ---


def test_api_rejects_non_http_base_url(client):
    res = client.post(
        "/api/providers",
        json={
            "name": "bad",
            "type": "openai_compat",
            "base_url": "ftp://example.com/v1",
            "api_key": FAKE_KEY,
        },
    )
    assert res.status_code == 422
    assert "base_url must be an http(s) URL" in res.text


def test_api_accepts_local_ollama_base_url(client):
    res = client.post(
        "/api/providers",
        json={
            "name": "ollama-local",
            "type": "openai_compat",
            "base_url": "http://127.0.0.1:11434/v1",
        },
    )
    assert res.status_code == 200
    assert res.json()["base_url"] == "http://127.0.0.1:11434/v1"


def test_api_patch_rejects_non_http_base_url(client):
    pid = client.post(
        "/api/providers",
        json={
            "name": "ok",
            "type": "openai_compat",
            "base_url": "http://127.0.0.1:11434/v1",
        },
    ).json()["id"]
    res = client.patch(f"/api/providers/{pid}", json={"base_url": "file:///etc/passwd"})
    assert res.status_code == 422
    assert "base_url must be an http(s) URL" in res.text


# --- validated_get（出站 GET 唯一收口；httpx.get 全 mock，不触网） ---


def test_validated_get_forwards_args_and_calls_once(monkeypatch):
    """合法 http URL：参数原样透传给 httpx.get，且只调用一次。"""
    calls: list[dict] = []
    sentinel = httpx.Response(
        200, request=httpx.Request("GET", "http://api.example.com/v1")
    )

    def fake_get(url, **kwargs):  # noqa: ANN001
        calls.append({"url": url, **kwargs})
        return sentinel

    monkeypatch.setattr("app.security.url_guard.httpx.get", fake_get)

    resp = validated_get(
        "http://api.example.com/v1",
        headers={"Authorization": "Bearer test-token"},
        timeout=12.5,
    )

    assert resp is sentinel
    assert len(calls) == 1
    assert calls[0]["url"] == "http://api.example.com/v1"
    assert calls[0]["headers"] == {"Authorization": "Bearer test-token"}
    assert calls[0]["timeout"] == 12.5


def test_validated_get_rejects_ftp_without_calling_httpx(monkeypatch):
    """ftp:// 等非法 scheme：就地抛 ValueError，httpx.get 绝不被调用。"""

    def fake_get(url, **kwargs):  # noqa: ANN001
        raise AssertionError("httpx.get must not be called for an invalid scheme")

    monkeypatch.setattr("app.security.url_guard.httpx.get", fake_get)

    with pytest.raises(ValueError) as excinfo:
        validated_get("ftp://example.com/files")
    assert "ftp" in str(excinfo.value)
    # 若 httpx.get 被调用，fake_get 会以 AssertionError 失败，测试自动不通过。


def test_validated_get_passes_follow_redirects(monkeypatch):
    """follow_redirects 透传：显式 True 传 True，缺省时为 False。"""
    calls: list[dict] = []

    def fake_get(url, **kwargs):  # noqa: ANN001
        calls.append({"url": url, **kwargs})
        return httpx.Response(200, request=httpx.Request("GET", url))

    monkeypatch.setattr("app.security.url_guard.httpx.get", fake_get)

    validated_get("http://example.com/explicit", follow_redirects=True)
    validated_get("http://example.com/default")

    assert len(calls) == 2
    assert calls[0]["follow_redirects"] is True
    assert calls[1]["follow_redirects"] is False


# --- fetch_arxiv 重定向防护（网络全 mock，不触网） ---


class _RedirectPdfResult:
    """Minimal stand-in for an ``arxiv.Result`` with a downloadable pdf_url."""

    def __init__(self, pdf_url: str) -> None:
        self.title = "A Paper"
        self.authors = ["Alice"]
        self.summary = "An abstract"
        self.published = None
        self.pdf_url = pdf_url
        self.doi = None


class _RedirectPdfClient:
    def __init__(self, pdf_url: str) -> None:
        self.pdf_url = pdf_url

    def results(self, search):  # noqa: ANN001
        return iter([_RedirectPdfResult(self.pdf_url)])


class _ShortIdPdfResult:
    """arxiv.Result stand-in with get_short_id() and a decoy pdf_url."""

    def __init__(self) -> None:
        self.title = "A Paper"
        self.authors = ["Alice"]
        self.summary = "An abstract"
        self.published = None
        self.pdf_url = "http://attacker.example/decoy.pdf"  # 必须被忽略
        self.doi = None

    def get_short_id(self) -> str:
        return "2405.00001v2"


class _ShortIdPdfClient:
    def results(self, search):  # noqa: ANN001
        return iter([_ShortIdPdfResult()])


def test_fetch_arxiv_downloads_constructed_short_id_url(monkeypatch):
    """下载 URL 必须由 get_short_id() 构造成 https://arxiv.org/pdf/{short_id}，
    result.pdf_url 即使存在（哪怕是攻击者可控的值）也不得被使用。"""
    calls: list[str] = []

    def fake_get(url, **kwargs):  # noqa: ANN001
        calls.append(url)
        return httpx.Response(
            200, content=b"pdf-bytes", request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    fp = fetch_arxiv("2405.00001", client=_ShortIdPdfClient())
    assert calls == ["https://arxiv.org/pdf/2405.00001v2"]
    assert fp.pdf_bytes == b"pdf-bytes"


def test_fetch_arxiv_rejects_redirect_to_non_arxiv_host(monkeypatch):
    """首跳 302 Location 指向任意主机：必须 ValueError，且绝不发起第二次请求。"""
    calls: list[str] = []
    kwargs_seen: list[dict] = []

    def fake_get(url, **kwargs):  # noqa: ANN001
        calls.append(url)
        kwargs_seen.append(kwargs)
        return httpx.Response(
            302,
            headers={"location": "https://evil.com/pdf"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(ValueError):
        fetch_arxiv(
            "2405.00001", client=_RedirectPdfClient("https://arxiv.org/pdf/2405.00001")
        )
    assert calls == ["https://arxiv.org/pdf/2405.00001"]
    assert kwargs_seen[0].get("follow_redirects") is False


def test_fetch_arxiv_follows_redirect_within_arxiv(monkeypatch):
    """302 到 export.arxiv.org 再 200：放行并成功拿到字节。"""

    def fake_get(url, **kwargs):  # noqa: ANN001
        assert kwargs.get("follow_redirects") is False
        if url == "https://arxiv.org/pdf/2405.00001":
            return httpx.Response(
                302,
                headers={"location": "https://export.arxiv.org/pdf/x"},
                request=httpx.Request("GET", url),
            )
        return httpx.Response(
            200, content=b"pdf-bytes", request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    fp = fetch_arxiv(
        "2405.00001", client=_RedirectPdfClient("https://arxiv.org/pdf/2405.00001")
    )
    assert fp.pdf_bytes == b"pdf-bytes"


def test_fetch_arxiv_resolves_relative_redirect_location(monkeypatch):
    """相对 Location（/pdf/new）须先 urljoin 成绝对 URL、校验通过后放行。"""
    calls: list[str] = []
    kwargs_seen: list[dict] = []

    def fake_get(url, **kwargs):  # noqa: ANN001
        calls.append(url)
        kwargs_seen.append(kwargs)
        if len(calls) == 1:
            return httpx.Response(
                302,
                headers={"location": "/pdf/new"},
                request=httpx.Request("GET", url),
            )
        return httpx.Response(200, content=b"ok", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)

    fp = fetch_arxiv(
        "2405.00001", client=_RedirectPdfClient("https://arxiv.org/pdf/2405.00001")
    )
    assert fp.pdf_bytes == b"ok"
    assert calls == ["https://arxiv.org/pdf/2405.00001", "https://arxiv.org/pdf/new"]
    assert all(kw.get("follow_redirects") is False for kw in kwargs_seen)
