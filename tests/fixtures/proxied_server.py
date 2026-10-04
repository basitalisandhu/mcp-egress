"""Fixture MCP server whose tools honour proxy variables.

`fetch` uses urllib, which reads HTTP_PROXY, HTTPS_PROXY and NO_PROXY from the
environment and sends absolute-form requests through the proxy. `tunnel` reads
HTTPS_PROXY itself and speaks CONNECT, which is the path an HTTPS client takes.
`ping` does the same as `fetch` but declares `openWorldHint: false`, so the
audit can flag the contradiction. `echo`, `env` and `sleep` never touch the
network. The base URL used by `ping` comes from `--base-url`, if given, which
also lets a test declare a base URL on the command line.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

server = MCPServer("proxied-fixture", version="0.1.0")
BASE_URL = ""
for index, token in enumerate(sys.argv):
    if token == "--base-url" and index + 1 < len(sys.argv):
        BASE_URL = sys.argv[index + 1]
    elif token.startswith("--base-url="):
        BASE_URL = token.split("=", 1)[1]


def _get(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            body = resp.read().decode("utf-8", "replace")
            return f"{resp.status} {resp.reason}\n{body}"
    except urllib.error.HTTPError as exc:
        return f"{exc.code} {exc.reason}\n{exc.read().decode('utf-8', 'replace')}"


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
def fetch(url: str) -> str:
    """Fetch a URL with urllib (honours proxy variables) and return status and body."""
    return _get(url)


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def ping(url: str = "") -> str:
    """Claims to be closed-world but fetches `url` (or the base URL) anyway."""
    return _get(url or BASE_URL)


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
def tunnel(url: str) -> str:
    """Send a GET through HTTPS_PROXY using CONNECT, the way an HTTPS client would."""
    proxy = urlsplit(os.environ["HTTPS_PROXY"])
    target = urlsplit(url)
    port = target.port or 80
    with socket.create_connection((proxy.hostname, proxy.port), timeout=10) as sock:
        authority = f"{target.hostname}:{port}"
        sock.sendall(f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n\r\n".encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = sock.recv(4096)
            if not chunk:
                return "proxy closed the connection"
            head += chunk
        status_line = head.split(b"\r\n", 1)[0].decode()
        if " 200 " not in status_line:
            return f"CONNECT failed: {status_line}"
        path = target.path or "/"
        sock.sendall(
            f"GET {path} HTTP/1.1\r\nHost: {authority}\r\nConnection: close\r\n\r\n".encode()
        )
        data = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
    text = data.decode("utf-8", "replace")
    first = text.split("\r\n", 1)[0]
    body = text.split("\r\n\r\n", 1)[1] if "\r\n\r\n" in text else ""
    return f"{first.split(' ', 1)[1]}\n{body}"


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def echo(text: str) -> str:
    """Return the text unchanged. Never touches the network."""
    return text


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def env() -> str:
    """Return the proxy-related environment the server was started with, as JSON."""
    names = [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
        "NODE_USE_ENV_PROXY",
        "MCP_EGRESS_TEST_MARKER",
    ]
    return json.dumps({name: os.environ.get(name) for name in names})


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def sleep(seconds: float) -> str:
    """Sleep for `seconds` without blocking the server. Used to exercise the timeout."""
    await anyio.sleep(seconds)
    return f"slept {seconds}"


if __name__ == "__main__":
    server.run("stdio")
