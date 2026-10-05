"""The recording proxy on its own: CONNECT, absolute-form, errors, attribution."""

from __future__ import annotations

import asyncio

import pytest

from mcp_egress.proxy import (
    ProxyError,
    RecordingProxy,
    parse_absolute_target,
    parse_connect_target,
    parse_head,
)
from mcp_egress.recorder import PHASE_CALL, PHASE_LIST, Recorder


async def _exchange(port: int, payload: bytes) -> bytes:
    """Send `payload` to the proxy and read until it closes the connection."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(payload)
    await writer.drain()
    data = await reader.read(-1)
    writer.close()
    await writer.wait_closed()
    return data


def test_connect_tunnels_bytes_and_records_the_host(http_server):
    async def go():
        recorder = Recorder()
        recorder.set_phase(PHASE_CALL, "fetch")
        async with RecordingProxy(recorder) as proxy:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
            writer.write(
                f"CONNECT {http_server.key} HTTP/1.1\r\nHost: {http_server.key}\r\n\r\n".encode()
            )
            await writer.drain()
            head = await reader.readuntil(b"\r\n\r\n")
            writer.write(b"GET /tunnelled HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
            await writer.drain()
            body = await reader.read(-1)
            writer.close()
            await writer.wait_closed()
            return recorder, head, body

    recorder, head, body = asyncio.run(go())
    assert head.startswith(b"HTTP/1.1 200")
    assert b"hello from the test server" in body
    assert http_server.requests == ["GET /tunnelled HTTP/1.1"]
    assert len(recorder.connections) == 1
    conn = recorder.connections[0]
    assert (conn.host, conn.port, conn.scheme) == ("127.0.0.1", http_server.port, "https")
    assert (conn.phase, conn.tool) == (PHASE_CALL, "fetch")
    assert conn.connected and conn.bytes_out > 0 and conn.bytes_in > 0
    assert recorder.hosts()[0].to_dict()["addresses"] == ["127.0.0.1"]


def test_absolute_form_request_is_forwarded_and_recorded_as_http(http_server):
    async def go():
        recorder = Recorder()
        recorder.set_phase(PHASE_LIST)
        async with RecordingProxy(recorder) as proxy:
            request = (
                f"GET {http_server.url}/abs?x=1 HTTP/1.1\r\nHost: {http_server.key}\r\n"
                "Proxy-Connection: keep-alive\r\nUser-Agent: t\r\n\r\n"
            ).encode()
            return recorder, await _exchange(proxy.port, request)

    recorder, data = asyncio.run(go())
    assert data.startswith(b"HTTP/1.0 200") or data.startswith(b"HTTP/1.1 200")
    assert b"hello from the test server" in data
    assert http_server.requests == ["GET /abs?x=1 HTTP/1.1"]
    conn = recorder.connections[0]
    assert (conn.host, conn.port, conn.scheme, conn.phase, conn.tool) == (
        "127.0.0.1",
        http_server.port,
        "http",
        PHASE_LIST,
        None,
    )
    assert conn.bytes_in == len(data)
    assert recorder.hosts()[0].to_dict()["addresses"] == ["127.0.0.1"]


def test_origin_form_and_garbage_get_400_and_are_not_recorded():
    async def go():
        recorder = Recorder()
        async with RecordingProxy(recorder) as proxy:
            a = await _exchange(proxy.port, b"GET /relative HTTP/1.1\r\nHost: x\r\n\r\n")
            b = await _exchange(proxy.port, b"not http at all\r\n\r\n")
            return recorder, a, b

    recorder, a, b = asyncio.run(go())
    assert a.startswith(b"HTTP/1.1 400")
    assert b.startswith(b"HTTP/1.1 400")
    assert recorder.connections == []


def test_unreachable_upstream_gets_502_but_the_attempt_is_recorded():
    async def go():
        recorder = Recorder()
        async with RecordingProxy(recorder) as proxy:
            data = await _exchange(proxy.port, b"CONNECT 127.0.0.1:1 HTTP/1.1\r\n\r\n")
            return recorder, data

    recorder, data = asyncio.run(go())
    assert data.startswith(b"HTTP/1.1 502")
    assert len(recorder.connections) == 1
    assert recorder.connections[0].connected is False
    assert recorder.connections[0].key == "127.0.0.1:1"
    assert recorder.hosts()[0].to_dict()["addresses"] == []


def test_proxy_listens_on_loopback_only_with_an_ephemeral_port():
    async def go():
        async with RecordingProxy(Recorder()) as proxy:
            return proxy.url, proxy.bound_address

    url, (host, port) = asyncio.run(go())
    assert host == "127.0.0.1"
    assert port > 1024
    assert url == f"http://127.0.0.1:{port}"


def test_hosts_aggregate_per_host_port_and_scheme(http_server):
    async def go():
        recorder = Recorder()
        async with RecordingProxy(recorder) as proxy:
            recorder.set_phase(PHASE_LIST)
            req = f"GET {http_server.url}/ HTTP/1.1\r\nHost: {http_server.key}\r\n\r\n".encode()
            await _exchange(proxy.port, req)
            recorder.set_phase(PHASE_CALL, "search")
            await _exchange(proxy.port, req)
            recorder.set_phase(PHASE_CALL, "fetch")
            await _exchange(proxy.port, req)
            return recorder

    recorder = asyncio.run(go())
    hosts = recorder.hosts()
    assert len(hosts) == 1
    rec = hosts[0]
    assert rec.connections == 3
    assert rec.to_dict()["addresses"] == ["127.0.0.1"]
    assert rec.phase == PHASE_LIST and rec.tool is None
    assert rec.phases == [PHASE_LIST, PHASE_CALL]
    assert rec.tools == ["search", "fetch"]
    assert rec.bytes_in == sum(c.bytes_in for c in recorder.connections)
    assert recorder.keys_since(1) == [http_server.key]


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("example.com:443", ("example.com", 443)),
        ("[::1]:8443", ("::1", 8443)),
        ("127.0.0.1:80", ("127.0.0.1", 80)),
    ],
)
def test_parse_connect_target(target, expected):
    assert parse_connect_target(target) == expected


@pytest.mark.parametrize(
    "target", ["example.com", ":443", "example.com:x", "example.com:70000", "[::1]"]
)
def test_parse_connect_target_rejects_bad_input(target):
    with pytest.raises(ProxyError):
        parse_connect_target(target)


def test_parse_absolute_target_and_head():
    assert parse_absolute_target("http://example.com/a/b?c=1") == ("example.com", 80, "/a/b?c=1")
    assert parse_absolute_target("http://example.com:8080") == ("example.com", 8080, "/")
    with pytest.raises(ProxyError):
        parse_absolute_target("https://example.com/")
    method, target, version, headers = parse_head(
        b"GET http://h/ HTTP/1.1\r\nHost: h\r\nX: y\r\n\r\n"
    )
    assert (method, target, version) == ("GET", "http://h/", "HTTP/1.1")
    assert headers == [("Host", "h"), ("X", "y")]
    with pytest.raises(ProxyError):
        parse_head(b"GET /\r\n\r\n")


def test_host_addresses_are_distinct_in_connection_order():
    recorder = Recorder()
    for address in ["127.0.0.2", "::1", "127.0.0.2"]:
        conn = recorder.open("example.test", 443, "https")
        conn.connected = True
        conn.address = address
    failed = recorder.open("example.test", 443, "https")
    failed.address = "127.0.0.3"
    assert recorder.hosts()[0].to_dict()["addresses"] == ["127.0.0.2", "::1"]
