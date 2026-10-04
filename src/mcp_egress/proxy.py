"""A small asyncio HTTP proxy that records where connections go.

It accepts two request shapes from the server under test:

- `CONNECT host:port HTTP/1.1`: answers `200 Connection Established` and
  tunnels bytes both ways without looking at them (this is how HTTPS goes
  through a proxy).
- `GET http://host[:port]/path HTTP/1.1` (absolute-form, any method): opens a
  connection to the host, rewrites the request line to origin-form and relays
  the request and the response.

The proxy listens on 127.0.0.1 only, on an ephemeral port, and records the
host, port and byte counts of every connection. It records hosts, not payloads.
"""

from __future__ import annotations

import asyncio
import contextlib
from urllib.parse import urlsplit

from .recorder import SCHEME_PLAIN, SCHEME_TUNNEL, Connection, Recorder

LISTEN_HOST = "127.0.0.1"
HEADER_TIMEOUT = 30.0
CONNECT_TIMEOUT = 10.0
CHUNK = 65536

# Hop-by-hop headers that must not be forwarded to the upstream server.
_HOP_BY_HOP = {
    "proxy-connection",
    "proxy-authorization",
    "proxy-authenticate",
    "connection",
    "keep-alive",
    "te",
    "trailer",
    "upgrade",
}


class ProxyError(Exception):
    """A malformed request from the client."""


def parse_connect_target(target: str) -> tuple[str, int]:
    """Split the `host:port` authority of a CONNECT request."""
    if target.startswith("["):
        end = target.find("]")
        if end < 0 or not target[end + 1 :].startswith(":"):
            raise ProxyError(f"bad CONNECT target {target!r}")
        host, port_text = target[1:end], target[end + 2 :]
    else:
        host, sep, port_text = target.rpartition(":")
        if not sep or not host:
            raise ProxyError(f"bad CONNECT target {target!r}")
    try:
        port = int(port_text)
    except ValueError:
        raise ProxyError(f"bad CONNECT port {port_text!r}") from None
    if not 0 < port < 65536:
        raise ProxyError(f"bad CONNECT port {port}")
    return host, port


def parse_absolute_target(target: str) -> tuple[str, int, str]:
    """Split an absolute-form request target into host, port and origin-form path."""
    parts = urlsplit(target)
    if parts.scheme.lower() != "http" or not parts.hostname:
        raise ProxyError(f"unsupported request target {target!r}")
    port = parts.port or 80
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    return parts.hostname, port, path


def parse_head(head: bytes) -> tuple[str, str, str, list[tuple[str, str]]]:
    """Parse the request line and headers of an HTTP/1.x request head."""
    try:
        text = head.decode("iso-8859-1")
    except UnicodeDecodeError:  # pragma: no cover - iso-8859-1 decodes any byte
        raise ProxyError("undecodable request head") from None
    lines = text.split("\r\n")
    parts = lines[0].split(" ")
    if len(parts) != 3 or not parts[2].startswith("HTTP/1."):
        raise ProxyError(f"bad request line {lines[0]!r}")
    headers: list[tuple[str, str]] = []
    for line in lines[1:]:
        if not line:
            continue
        name, sep, value = line.partition(":")
        if not sep:
            raise ProxyError(f"bad header line {line!r}")
        headers.append((name.strip(), value.strip()))
    return parts[0], parts[1], parts[2], headers


class RecordingProxy:
    """The CONNECT and absolute-form proxy, bound to a `Recorder`."""

    def __init__(self, recorder: Recorder) -> None:
        self.recorder = recorder
        self._server: asyncio.AbstractServer | None = None
        self._tasks: set[asyncio.Task] = set()
        self.port: int = 0

    @property
    def url(self) -> str:
        return f"http://{LISTEN_HOST}:{self.port}"

    @property
    def bound_address(self) -> tuple[str, int]:
        """The (host, port) the listening socket is bound to."""
        if self._server is None:
            raise RuntimeError("proxy is not running")
        return self._server.sockets[0].getsockname()[:2]

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, LISTEN_HOST, 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def close(self) -> None:
        if self._server is None:
            return
        self._server.close()
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        with contextlib.suppress(Exception):
            await self._server.wait_closed()
        self._server = None

    async def __aenter__(self) -> RecordingProxy:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._tasks.add(task)
        try:
            await self._serve(reader, writer)
        except asyncio.CancelledError:
            pass
        except Exception:  # a broken client must not take the proxy down
            pass
        finally:
            if task is not None:
                self._tasks.discard(task)
            await _close_writer(writer)

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HEADER_TIMEOUT)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
            return
        try:
            method, target, version, headers = parse_head(head)
            if method.upper() == "CONNECT":
                host, port = parse_connect_target(target)
                await self._tunnel(reader, writer, host, port)
            elif target.lower().startswith("http://"):
                host, port, path = parse_absolute_target(target)
                await self._forward(reader, writer, host, port, method, path, version, headers)
            else:
                raise ProxyError(f"only CONNECT and absolute-form requests are proxied: {target!r}")
        except ProxyError as exc:
            await _reply(writer, 400, "Bad Request", str(exc))

    async def _tunnel(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, host: str, port: int
    ) -> None:
        conn = self.recorder.open(host, port, SCHEME_TUNNEL)
        upstream = await self._connect(writer, conn)
        if upstream is None:
            return
        up_reader, up_writer = upstream
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await self._pump_both(reader, writer, up_reader, up_writer, conn)

    async def _forward(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        host: str,
        port: int,
        method: str,
        path: str,
        version: str,
        headers: list[tuple[str, str]],
    ) -> None:
        conn = self.recorder.open(host, port, SCHEME_PLAIN)
        upstream = await self._connect(writer, conn)
        if upstream is None:
            return
        up_reader, up_writer = upstream
        lines = [f"{method} {path} {version}"]
        lines.extend(
            f"{name}: {value}" for name, value in headers if name.lower() not in _HOP_BY_HOP
        )
        lines.append("Connection: close")
        request = ("\r\n".join(lines) + "\r\n\r\n").encode("iso-8859-1")
        conn.bytes_out += len(request)
        up_writer.write(request)
        await up_writer.drain()
        await self._pump_both(reader, writer, up_reader, up_writer, conn)

    async def _connect(
        self, writer: asyncio.StreamWriter, conn: Connection
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter] | None:
        try:
            up_reader, up_writer = await asyncio.wait_for(
                asyncio.open_connection(conn.host, conn.port), CONNECT_TIMEOUT
            )
        except (OSError, TimeoutError) as exc:
            await _reply(writer, 502, "Bad Gateway", f"cannot reach {conn.key}: {exc}")
            return None
        conn.connected = True
        return up_reader, up_writer

    async def _pump_both(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        up_reader: asyncio.StreamReader,
        up_writer: asyncio.StreamWriter,
        conn: Connection,
    ) -> None:
        try:
            await asyncio.gather(
                _pump(reader, up_writer, conn, "bytes_out"),
                _pump(up_reader, writer, conn, "bytes_in"),
            )
        finally:
            await _close_writer(up_writer)


async def _pump(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, conn: Connection, counter: str
) -> None:
    try:
        while True:
            data = await reader.read(CHUNK)
            if not data:
                break
            setattr(conn, counter, getattr(conn, counter) + len(data))
            writer.write(data)
            await writer.drain()
    except (OSError, asyncio.IncompleteReadError):
        pass
    finally:
        if writer.can_write_eof() and not writer.is_closing():
            with contextlib.suppress(OSError):
                writer.write_eof()


async def _reply(writer: asyncio.StreamWriter, status: int, reason: str, body: str) -> None:
    payload = body.encode("utf-8", "replace")
    head = (
        f"HTTP/1.1 {status} {reason}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        f"Content-Length: {len(payload)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("iso-8859-1")
    with contextlib.suppress(OSError):
        writer.write(head + payload)
        await writer.drain()


async def _close_writer(writer: asyncio.StreamWriter) -> None:
    if writer.is_closing():
        return
    with contextlib.suppress(OSError):
        writer.close()
        await writer.wait_closed()
