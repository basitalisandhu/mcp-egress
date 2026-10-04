"""Shared fixtures: a local HTTP test server and the paths of the fixture MCP servers.

The test process may itself sit behind an outer HTTPS proxy (HTTPS_PROXY set,
NO_PROXY listing loopback). Nothing here depends on that: the test server binds
127.0.0.1, the recording proxy connects to it directly, and mcp-egress sets the
child's proxy variables explicitly and clears NO_PROXY, so the recording proxy
is the one the fixture servers use.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
PROXIED_SERVER = FIXTURES / "proxied_server.py"
SOCKET_SERVER = FIXTURES / "socket_server.py"


@dataclass
class TestHttpServer:
    host: str
    port: int
    requests: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def key(self) -> str:
        return f"{self.host}:{self.port}"


class _Handler(BaseHTTPRequestHandler):
    server_version = "mcp-egress-test/1"
    state: TestHttpServer

    def do_GET(self) -> None:
        self.state.requests.append(self.requestline)
        if self.path.startswith("/status/"):
            code = int(self.path.rsplit("/", 1)[1])
            body = f"status {code}".encode()
            self.send_response(code)
        else:
            body = b"hello from the test server"
            self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture
def http_server() -> TestHttpServer:
    """A plain HTTP server on 127.0.0.1 that records every request line it serves."""
    state = TestHttpServer("127.0.0.1", 0)
    handler = type("Handler", (_Handler,), {"state": state})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    state.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def proxied_command() -> list[str]:
    return [sys.executable, str(PROXIED_SERVER)]


@pytest.fixture
def socket_command() -> list[str]:
    return [sys.executable, str(SOCKET_SERVER)]


@pytest.fixture
def server_log(tmp_path: Path):
    """An open file for the fixture server's stderr, so pytest capture is not involved."""
    with open(tmp_path / "server.log", "w", encoding="utf-8") as fh:
        yield fh
