"""External interfaces that expose PaperMind to other local AI tools.

``mcp_server`` implements the MCP (Model Context Protocol) Streamable HTTP
endpoint mounted at ``/api/mcp`` — the same literature tools the in-app chat
assistant uses, offered to external clients such as Claude Code or Codex.
"""
