"""Connection records and the phase/tool context they are attributed to."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

PHASE_STARTUP = "startup"
PHASE_LIST = "list"
PHASE_CALL = "call"
PHASE_SHUTDOWN = "shutdown"

SCHEME_TUNNEL = "https"  # CONNECT tunnels; the proxy never sees inside them
SCHEME_PLAIN = "http"  # absolute-form requests forwarded in the clear


def utc_now() -> str:
    """Current time as an ISO 8601 UTC timestamp with second precision."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def host_key(host: str, port: int) -> str:
    """The `host:port` string used for baselines and per-tool host lists."""
    return f"{host}:{port}"


@dataclass
class Connection:
    """One proxied connection, as recorded by the proxy."""

    host: str
    port: int
    scheme: str
    phase: str
    tool: str | None
    first_seen: str
    bytes_out: int = 0
    bytes_in: int = 0
    connected: bool = False

    @property
    def key(self) -> str:
        return host_key(self.host, self.port)


@dataclass
class HostRecord:
    """All connections to one host, port and scheme, aggregated."""

    host: str
    port: int
    scheme: str
    phase: str
    tool: str | None
    first_seen: str
    bytes_out: int = 0
    bytes_in: int = 0
    connections: int = 0
    phases: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return host_key(self.host, self.port)

    def to_dict(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "scheme": self.scheme,
            "phase": self.phase,
            "tool": self.tool,
            "first_seen": self.first_seen,
            "bytes_out": self.bytes_out,
            "bytes_in": self.bytes_in,
            "connections": self.connections,
            "phases": list(self.phases),
            "tools": list(self.tools),
        }


class Recorder:
    """Keeps the list of connections and the phase and tool they belong to.

    The runner sets the phase before each step; the proxy calls `open()` when a
    client request arrives. Both run on the same event loop, so the context seen
    by `open()` is the step that was in progress when the connection was made.
    """

    def __init__(self) -> None:
        self.phase: str = PHASE_STARTUP
        self.tool: str | None = None
        self.connections: list[Connection] = []

    def set_phase(self, phase: str, tool: str | None = None) -> None:
        self.phase = phase
        self.tool = tool

    def open(self, host: str, port: int, scheme: str) -> Connection:
        conn = Connection(
            host=host.lower(),
            port=port,
            scheme=scheme,
            phase=self.phase,
            tool=self.tool,
            first_seen=utc_now(),
        )
        self.connections.append(conn)
        return conn

    def hosts(self) -> list[HostRecord]:
        """Aggregate connections per (host, port, scheme) in first-seen order."""
        records: dict[tuple[str, int, str], HostRecord] = {}
        for conn in self.connections:
            key = (conn.host, conn.port, conn.scheme)
            rec = records.get(key)
            if rec is None:
                rec = HostRecord(
                    host=conn.host,
                    port=conn.port,
                    scheme=conn.scheme,
                    phase=conn.phase,
                    tool=conn.tool,
                    first_seen=conn.first_seen,
                )
                records[key] = rec
            rec.connections += 1
            rec.bytes_out += conn.bytes_out
            rec.bytes_in += conn.bytes_in
            if conn.phase not in rec.phases:
                rec.phases.append(conn.phase)
            if conn.tool and conn.tool not in rec.tools:
                rec.tools.append(conn.tool)
        return list(records.values())

    def keys_since(self, index: int) -> list[str]:
        """Distinct `host:port` keys of connections recorded from `index` on."""
        seen: list[str] = []
        for conn in self.connections[index:]:
            if conn.key not in seen:
                seen.append(conn.key)
        return seen
