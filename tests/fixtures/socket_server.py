"""Fixture MCP server whose tools ignore proxy variables.

`fetch` opens a TCP connection straight to the target host with `http.client`,
which never reads HTTP_PROXY or HTTPS_PROXY. mcp-egress sees no proxied
connection during the call although the result looks like network output, so
it prints the possible-proxy-bypass warning.
"""

from __future__ import annotations

import http.client
from urllib.parse import urlsplit

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

server = MCPServer("socket-fixture", version="0.1.0")


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
def fetch(url: str) -> str:
    """Fetch a URL with a direct socket connection, bypassing any proxy."""
    parts = urlsplit(url)
    conn = http.client.HTTPConnection(parts.hostname or "", parts.port or 80, timeout=10)
    try:
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", "replace")
        return f"{resp.status} {resp.reason}\n{body}"
    finally:
        conn.close()


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def quiet() -> str:
    """Return a plain string with nothing network-shaped in it."""
    return "all quiet"


if __name__ == "__main__":
    server.run("stdio")
