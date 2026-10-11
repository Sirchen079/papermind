"""MCP (Model Context Protocol) endpoint: expose PaperMind's literature tools to external AI clients.

External clients (Claude Code / Codex …) connect over Streamable HTTP::

    {"type": "http", "url": "http://127.0.0.1:<port>/api/w/<workspace_id>/mcp",
     "headers": {"X-Local-Token": "<api_token>"}}

- Reuses the in-app tool registry ``app.agent.tools.TOOLS``: external clients and
  the built-in chat assistant see the same literature tools.
- Workspace isolation: ``/api/w/<id>/mcp`` is rewritten to ``/api/mcp`` by
  ``WorkspaceMiddleware`` with the workspace bound. Because the MCP session
  manager serves requests from its own task group (the request's ContextVars do
  not propagate into it), this module's ASGI wrapper copies the bound
  ``WorkspaceContext`` into the ASGI scope; the tool work is then wrapped in
  ``bind_workspace`` on the worker thread, so tools open the session for the
  right workspace database.
- Authentication: the wrapper checks the local API token first
  (``X-Local-Token`` or ``Authorization: Bearer``) and returns 401 before any
  MCP processing.

The SDK installs as the ``mcp`` package; this module is deliberately named
``mcp_server`` so it can never shadow it.
"""

from __future__ import annotations

import logging
import secrets
import threading

import anyio.to_thread
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import PaginatedRequestParams, Tool as MCPTool
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, TextContent
from sqlmodel import Session

from app.agent.tools import get_tool
from app.db.engine import get_engine
from app.security.local_token import get_or_create_token
from app.workspaces.context import bind_workspace, current_workspace

logger = logging.getLogger(__name__)

SERVER_NAME = "papermind"
SERVER_TITLE = "PaperMind 文献助手"
SERVER_VERSION = "0.1.0"

# The tool subset exposed over MCP: read/search tools plus the explicit write
# actions. Filtered by name *and* existence because the registry evolves
# (get_paper_card / read_literature_map are being added by another task and
# are only exposed once they actually exist).
READ_TOOL_NAMES = (
    "search_library",
    "get_paper",
    "get_paper_full_text",
    "get_paper_links",
    "search_paper_text",
    "search_research_notes",
    "read_paper_notes",
    "search_saved_documents",
    "read_saved_document",
    "read_review",
    "read_research_task",
    "search_topic_wiki",
    "get_paper_card",
    "read_literature_map",
    "list_builtin_skills",
    "load_builtin_skill",
    "read_builtin_skill_resource",
)
WRITE_TOOL_NAMES = (
    "save_paper_note",
    "save_research_idea",
    "save_document",
)
EXPOSED_TOOL_NAMES = READ_TOOL_NAMES + WRITE_TOOL_NAMES

# The registry is keyed by a plain dict; a lock keeps a concurrent re-register
# from racing the tool lookup during a call.
_registry_lock = threading.Lock()

# ASGI scope key carrying the request's WorkspaceContext into the MCP task.
WORKSPACE_SCOPE_KEY = "papermind.workspace_context"

_AUTH_BODY = ('{"error": "unauthorized", "message": "缺少或无效的本地访问令牌'
              '（X-Local-Token 或 Authorization: Bearer）。"}').encode("utf-8")


def exposed_tools():
    """The subset of registry tools offered over MCP, in registry order."""
    with _registry_lock:
        return [tool for name in EXPOSED_TOOL_NAMES
                if (tool := get_tool(name)) is not None]


def _run_tool(name: str, arguments: dict) -> str:
    """Run one sync tool against the workspace database bound in this thread."""
    with _registry_lock:
        tool = get_tool(name)
    if tool is None:
        raise ValueError(f"unknown tool: {name}")
    session = Session(get_engine())
    try:
        allowed = set((tool.parameters.get("properties") or {}).keys())
        call_args = {key: value for key, value in (arguments or {}).items() if key in allowed}
        return tool.run(session, **call_args)
    finally:
        session.close()


def _run_tool_in_workspace(workspace, name: str, arguments: dict) -> str:
    with bind_workspace(workspace):
        return _run_tool(name, arguments)


async def _call_tool(workspace, name: str, arguments: dict) -> CallToolResult:
    try:
        text = await anyio.to_thread.run_sync(_run_tool_in_workspace, workspace, name, arguments)
    except Exception as exc:  # noqa: BLE001 — tool failures become isError results
        logger.exception("MCP tool %s failed", name)
        return CallToolResult(
            content=[TextContent(type="text", text=f"工具执行失败：{exc}")],
            is_error=True,
        )
    return CallToolResult(content=[TextContent(type="text", text=text)])


def _resolve_workspace(ctx):
    """Recover the request's workspace.

    Normally the wrapper put the bound context into the scope and the lowlevel
    Server hands us the starlette Request as ``ctx.request``. Fall back to the
    current ContextVar (in-process calls / lifespan-context propagation).
    """
    request = getattr(ctx, "request", None)
    if request is not None:
        workspace = getattr(request, "scope", {}).get(WORKSPACE_SCOPE_KEY)
        if workspace is not None:
            return workspace
    return current_workspace.get()


async def _list_tools(ctx, params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(
        tools=[MCPTool(name=tool.name, description=tool.description, input_schema=tool.parameters)
               for tool in exposed_tools()]
    )


async def _handle_call_tool(ctx, params: CallToolRequestParams) -> CallToolResult:
    name = params.name
    with _registry_lock:
        known = get_tool(name) is not None
    if not known or name not in EXPOSED_TOOL_NAMES:
        return CallToolResult(
            content=[TextContent(type="text", text=f"工具不存在或不允许通过 MCP 调用：{name}")],
            is_error=True,
        )
    workspace = _resolve_workspace(ctx)
    if workspace is None:
        return CallToolResult(
            content=[TextContent(type="text", text="当前请求未绑定研究工作台（请使用 /api/w/<workspace_id>/mcp 连接）。")],
            is_error=True,
        )
    return await _call_tool(workspace, name, params.arguments or {})


def create_server() -> Server:
    """The lowlevel MCP Server serving PaperMind's exposed tools."""
    return Server(
        SERVER_NAME,
        version=SERVER_VERSION,
        title=SERVER_TITLE,
        instructions=(
            "PaperMind 本地文献库工具。检索与阅读用只读工具；保存笔记、想法和文档用 save_* 工具。"
            "所有操作都作用于当前连接绑定研究工作台。"
        ),
        on_list_tools=_list_tools,
        on_call_tool=_handle_call_tool,
    )


def create_session_manager() -> StreamableHTTPSessionManager:
    """Stateless Streamable HTTP manager (tools only, no sessions)."""
    return StreamableHTTPSessionManager(
        app=create_server(),
        stateless=True,
        # The app already has a Host whitelist; allow the SDK's DNS-rebinding
        # protection for the regular local addresses so real clients connect.
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
        ),
    )


def _token_matches(scope) -> bool:
    presented = None
    for key, value in scope.get("headers") or []:
        if key == b"x-local-token":
            presented = value.decode("latin-1").strip()
        elif key == b"authorization":
            raw = value.decode("latin-1").strip()
            if raw.lower().startswith("bearer "):
                presented = raw[7:].strip()
    if not presented:
        return False
    expected = get_or_create_token()
    if not expected:
        return False  # fail closed when the installation token is pending
    return secrets.compare_digest(presented, expected)


async def _send_plain(send, status: int, body: bytes, headers=None) -> None:
    response_headers = [(b"content-type", b"text/plain; charset=utf-8"),
                        (b"content-length", str(len(body)).encode("ascii"))]
    if headers:
        response_headers.extend(headers)
    await send({"type": "http.response.start", "status": status, "headers": response_headers})
    await send({"type": "http.response.body", "body": body})


class MCPASGIApp:
    """ASGI wrapper: token check → workspace capture → Streamable HTTP session.

    A class instance (not a function) is registered via ``app.add_route(...)``
    so Starlette treats it as a pure ASGI app. Requests are only forwarded to
    the session manager after authentication.
    """

    def __init__(self, session_manager: StreamableHTTPSessionManager | None = None):
        self.session_manager = session_manager or create_session_manager()

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await _send_plain(send, 405, b"unsupported scope type")
            return
        if not _token_matches(scope):
            await _send_plain(send, 401, _AUTH_BODY)
            return
        scope = dict(scope)
        workspace = current_workspace.get()
        if workspace is not None:
            scope[WORKSPACE_SCOPE_KEY] = workspace
        response_started = False

        async def guarded_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.session_manager.handle_request(scope, receive, guarded_send)
        except RuntimeError:
            # The session manager raises RuntimeError when .run() has not been
            # entered (e.g. a TestClient that never triggers the app lifespan)
            # or has already shut down. Fail cleanly with 503 instead of 500.
            logger.warning("MCP session manager is not running; request rejected")
            if not response_started:
                await _send_plain(send, 503, b'{"error": "mcp session manager is not running"}')


def create_mcp_app(session_manager: StreamableHTTPSessionManager | None = None) -> MCPASGIApp:
    return MCPASGIApp(session_manager)
