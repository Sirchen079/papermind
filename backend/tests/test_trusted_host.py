"""P15 安全加固：TrustedHostMiddleware 行为测试。

Starlette 的 TrustedHostMiddleware（1.6.0）在匹配前对 Host 头做
``split(":")[0]`` 剥端口，因此允许列表按裸主机名配置即可端口无关；
非法 Host 返回 400（PlainTextResponse "Invalid host header"）。
"""

from fastapi.testclient import TestClient


def _client() -> TestClient:
    from app.main import create_app

    return TestClient(create_app())


def test_default_testserver_host_allowed(client):
    # conftest 的 TestClient 默认 base_url 即 http://testserver，必须放行。
    resp = client.get("/api/health")
    assert resp.status_code == 200


def test_localhost_host_allowed():
    resp = _client().get("/api/health", headers={"Host": "localhost"})
    assert resp.status_code == 200


def test_loopback_ip_host_allowed():
    resp = _client().get("/api/health", headers={"Host": "127.0.0.1"})
    assert resp.status_code == 200


def test_localhost_with_port_allowed():
    # 端口无关匹配：starlette 剥离 ":端口" 后再比对。
    resp = _client().get("/api/health", headers={"Host": "localhost:4278"})
    assert resp.status_code == 200


def test_evil_host_rejected_with_400():
    resp = _client().get("/api/health", headers={"Host": "evil.com"})
    assert resp.status_code == 400
    assert resp.text == "Invalid host header"


def test_evil_host_with_port_rejected():
    resp = _client().get("/api/health", headers={"Host": "evil.com:8080"})
    assert resp.status_code == 400
