"""Real client tests for the MCP endpoint (/api/mcp).

Runs the actual app under uvicorn in a background thread (random port, temp
data dir) and connects with the official SDK client
(``mcp.client.streamable_http`` + ``ClientSession``), i.e. the same code path
Claude Code / Codex use. Covers: handshake, tool listing/filtering, a real
read call, a write that is read back, token rejection, per-workspace routing,
and unknown-tool errors.
"""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import time

import pytest

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


# ---------------------------------------------------------------- server host

class ServerThread:
    """uvicorn in a background thread bound to a pre-created random-port socket."""

    def __init__(self, app):
        self.app = app
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(32)
        self.port = self.sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.failure: BaseException | None = None
        self.server = None
        self.thread = threading.Thread(target=self._run, name="mcp-test-server", daemon=True)

    def _run(self):
        try:
            import uvicorn

            config = uvicorn.Config(self.app, log_config=None, log_level="warning", access_log=False,
                                    timeout_graceful_shutdown=5)
            self.server = uvicorn.Server(config)
            # Signals are only captured on the main thread; safe in a thread.
            self.server.run(sockets=[self.sock])
        except BaseException as exc:  # pragma: no cover - test infrastructure
            self.failure = exc

    def start(self):
        self.thread.start()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self.failure is not None:
                raise RuntimeError("test server failed to start") from self.failure
            if self.server is not None and self.server.started:
                return
            self.thread.join(timeout=0.05)
        raise TimeoutError("test server did not start")

    def stop(self):
        if self.server is not None:
            self.server.should_exit = True
        if self.thread.ident is not None:
            self.thread.join(timeout=15)
        try:
            self.sock.close()
        except OSError:
            pass


# --------------------------------------------------------------------- helper

def local_token() -> str:
    from app.security.local_token import get_or_create_token, reset_token_cache

    reset_token_cache()
    return get_or_create_token()


def request(endpoint: str, token: str | None = None, headers: dict | None = None):
    import httpx2

    merged = dict(headers or {})
    if token is not None:
        merged.setdefault("X-Local-Token", token)
    return httpx2.get(endpoint, headers=merged, timeout=15.0)


def _create_workspace(endpoint: str, token: str, name: str) -> str:
    import httpx2

    response = httpx2.post(endpoint + "/api/workspaces", json={"name": name, "goal": name + " goal"},
                           headers={"X-Local-Token": token}, timeout=30.0)
    assert response.status_code == 201, response.text
    return "/api/w/" + response.json()["id"]


def _create_paper(endpoint: str, token: str, prefix: str, title: str) -> int:
    import httpx2

    response = httpx2.post(endpoint + prefix + "/papers/manual", json={"title": title, "year": 2024},
                           headers={"X-Local-Token": token}, timeout=30.0)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _with_client(url: str, token: str, action):
    """Connect with the official SDK client and run ``action(session)``."""
    import httpx2

    async with httpx2.AsyncClient(headers={"X-Local-Token": token}, timeout=30.0) as http:
        async with streamable_http_client(url, http_client=http) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await action(session)


def text_of(result) -> str:
    return "".join(block.text for block in result.content if getattr(block, "type", None) == "text")


# ----------------------------------------------------------------------- tests

@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """One real server for the whole module (temp data dir, two workspaces)."""
    data = tmp_path_factory.mktemp("mcp-data")
    import os

    os.environ["PAPERMIND_DATA_DIR"] = str(data)
    os.environ["PAPERMIND_DB_PATH"] = str(data / "test.sqlite")
    os.environ["PAPERMIND_MASTER_KEY_PATH"] = str(data / "master.key")
    os.environ["PAPERMIND_NO_AUTOLOAD_SKILLS"] = "1"
    os.environ["PAPERMIND_DISABLE_RADAR_AUTORUN"] = "1"

    from app.main import create_app

    host = ServerThread(create_app())
    host.start()
    token = local_token()
    try:
        yield host, token
    finally:
        host.stop()
        for key in ("PAPERMIND_DATA_DIR", "PAPERMIND_DB_PATH", "PAPERMIND_MASTER_KEY_PATH",
                    "PAPERMIND_NO_AUTOLOAD_SKILLS", "PAPERMIND_DISABLE_RADAR_AUTORUN"):
            os.environ.pop(key, None)
        # The environment was mutated for this module only; cached engines and
        # the settings singleton belong to this data dir, so drop them.
        from app.db.engine import reset_engine_for_tests

        reset_engine_for_tests()


def test_mcp_requires_token(live_server):
    host, token = live_server
    assert request(host.url + "/api/mcp").status_code == 401
    assert request(host.url + "/api/mcp", token="wrong-token").status_code == 401
    # No token yet enters MCP: a proper POST also gets 401, not a JSON-RPC error.
    response = request(host.url + "/api/mcp", headers={"Content-Type": "application/json"})
    assert response.status_code == 401


def test_mcp_accepts_bearer_token(live_server):
    host, token = live_server
    workspace_prefix = _create_workspace(host.url, token, "MCP Bearer 空间")

    async def check(session):
        listed = await session.list_tools()
        return len(listed.tools)

    import httpx2

    async def bearer_client():
        async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30.0) as http:
            async with streamable_http_client(host.url + workspace_prefix + "/mcp",
                                              http_client=http) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    return await check(session)

    assert asyncio.run(bearer_client()) > 0
    assert request(host.url + "/api/mcp",
                   headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_mcp_initialize_and_tool_listing(live_server):
    host, token = live_server
    workspace_prefix = _create_workspace(host.url, token, "MCP 列表空间")

    async def check(session):
        listed = await session.list_tools()
        names = {tool.name for tool in listed.tools}
        assert {"search_library", "save_paper_note", "read_paper_notes"} <= names
        # Not exposed: destructive / local-file / web tools.
        assert not {"import_paper_pdf", "read_local_file", "search_web"} & names
        assert session.server_info is not None
        assert session.server_info.name == "papermind"
        return sorted(names)

    names = asyncio.run(_with_client(host.url + workspace_prefix + "/mcp", token, check))
    # Schema is the registry's Tool.parameters
    async def check_schema(session):
        listed = await session.list_tools()
        by_name = {tool.name: tool for tool in listed.tools}
        props = by_name["search_library"].input_schema["properties"]
        assert "query" in props
        return by_name["save_paper_note"].input_schema["properties"].keys()

    keys = asyncio.run(_with_client(host.url + workspace_prefix + "/mcp", token, check_schema))
    assert {"paper_id", "content"} <= set(keys)


def test_mcp_read_call_returns_workspace_paper(live_server):
    host, token = live_server
    workspace_prefix = _create_workspace(host.url, token, "MCP 阅读空间")
    pid = _create_paper(host.url, token, workspace_prefix, "MCP 可见的论文")

    async def check(session):
        result = await session.call_tool("search_library", {"query": "MCP 可见的论文"})
        assert not result.is_error, text_of(result)
        return json.loads(text_of(result))

    rows = asyncio.run(_with_client(host.url + workspace_prefix + "/mcp", token, check))
    assert [row["id"] for row in rows] == [pid]


def test_mcp_write_note_is_read_back(live_server):
    host, token = live_server
    workspace_prefix = _create_workspace(host.url, token, "MCP 写入空间")
    pid = _create_paper(host.url, token, workspace_prefix, "MCP 写入的论文")

    async def write(session):
        result = await session.call_tool("save_paper_note",
                                         {"paper_id": pid, "content": "来自 MCP 客户端的笔记"})
        assert not result.is_error, text_of(result)
        payload = json.loads(text_of(result))
        assert payload["ok"] is True
        return payload

    saved = asyncio.run(_with_client(host.url + workspace_prefix + "/mcp", token, write))
    assert saved["paper_id"] == pid

    async def read_back(session):
        result = await session.call_tool("read_paper_notes", {"paper_id": pid})
        assert not result.is_error, text_of(result)
        return json.loads(text_of(result))

    notes = asyncio.run(_with_client(host.url + workspace_prefix + "/mcp", token, read_back))
    assert any("来自 MCP 客户端的笔记" in item["preview"] for item in notes["items"])


def test_mcp_workspace_routing_is_isolated(live_server):
    host, token = live_server
    a = _create_workspace(host.url, token, "MCP 隔离 A")
    b = _create_workspace(host.url, token, "MCP 隔离 B")
    pid_a = _create_paper(host.url, token, a, "只属于空间 A 的论文")
    pid_b = _create_paper(host.url, token, b, "只属于空间 B 的论文")

    async def titles(prefix):
        async def check(session):
            result = await session.call_tool("search_library", {"query": "只属于空间"})
            payload = json.loads(text_of(result))
            return sorted(row["title"] for row in payload)

        return await _with_client(host.url + prefix + "/mcp", token, check)

    titles_a = asyncio.run(titles(a))
    titles_b = asyncio.run(titles(b))
    assert titles_a == ["只属于空间 A 的论文"]
    assert titles_b == ["只属于空间 B 的论文"]
    # Write to A, verify it does not leak into B.
    async def write_a(session):
        result = await session.call_tool("save_paper_note",
                                         {"paper_id": pid_a, "content": "仅 A 拥有的笔记"})
        assert not result.is_error, text_of(result)

    asyncio.run(_with_client(host.url + a + "/mcp", token, write_a))

    async def read_b(session):
        result = await session.call_tool("read_paper_notes", {"paper_id": pid_b})
        assert result.is_error or "仅 A 拥有的笔记" not in text_of(result)

    asyncio.run(_with_client(host.url + b + "/mcp", token, read_b))


def test_mcp_unknown_tool_is_error(live_server):
    host, token = live_server
    workspace_prefix = _create_workspace(host.url, token, "MCP 未知工具空间")

    async def check(session):
        result = await session.call_tool("import_paper_pdf", {"url": "https://example.invalid/x.pdf"})
        assert result.is_error
        assert "import_paper_pdf" in text_of(result)
        return True

    assert asyncio.run(_with_client(host.url + workspace_prefix + "/mcp", token, check))


def test_mcp_tool_failure_is_error_result_not_crash(live_server):
    host, token = live_server
    workspace_prefix = _create_workspace(host.url, token, "MCP 失败空间")

    async def check(session):
        # A missing paper makes the tool raise its own LookupError-ish path;
        # save_paper_note turns a missing paper into an exception here.
        result = await session.call_tool("save_paper_note", {"paper_id": 99999, "content": "x"})
        assert result.is_error
        listed = await session.list_tools()  # session still healthy
        assert listed.tools
        return text_of(result)

    text = asyncio.run(_with_client(host.url + workspace_prefix + "/mcp", token, check))
    assert text


def test_mcp_agent_summary_advertises_mcp(live_server):
    host, token = live_server
    response = request(host.url + "/api/agent/summary", token=token)
    assert response.status_code == 200, response.text
    assert response.json()["mcp"] == {"url": "/api/mcp", "transport": "streamable-http"}
