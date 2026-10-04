"""Heuristics over a run: declared base URLs, network-shaped output, warnings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runner import RunResult

CODE_PROXY_BYPASS = "possible-proxy-bypass"
CODE_OPEN_WORLD = "open-world-hint-false"
CODE_OUTSIDE_BASE = "outside-declared-base-url"

_URL = re.compile(r"https?://[^\s\"'<>)\]]+", re.IGNORECASE)
_URL_HOST = re.compile(r"https?://(?:[^@/\s]*@)?(\[[0-9a-f:.]+\]|[^\s/:?#\"']+)", re.IGNORECASE)
# A line that looks like an HTTP status line or a bare status code with reason.
_STATUS_LINE = re.compile(r"^\s*(?:HTTP/\d(?:\.\d)?\s+)?[1-5]\d\d(?:\s+[A-Za-z][A-Za-z '-]*)?\s*$")
# `status: 200`, `status_code=404`, `"statusCode": 500` and similar.
_STATUS_FIELD = re.compile(
    r"\b(?:status[_ ]?code|statusCode|status)\b\W{0,3}([1-5]\d\d)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class Warning:
    code: str
    tool: str | None
    message: str

    def to_dict(self) -> dict:
        return {"code": self.code, "tool": self.tool, "message": self.message}


def network_evidence(text: str, ignore_urls: tuple[str, ...] = ()) -> str | None:
    """Return the fragment that makes `text` look like network output, or None.

    Evidence is an `http://` or `https://` URL, a status-code-shaped line such as
    `200 OK` or `HTTP/1.1 404 Not Found`, or a status field such as `status: 503`.
    URLs starting with one of `ignore_urls` (the recording proxy's own address)
    are not evidence: a server that echoes its environment is not calling out.
    """
    for match in _URL.finditer(text):
        url = match.group(0)
        if not any(url.startswith(prefix) for prefix in ignore_urls):
            return url
    for line in text.splitlines():
        if _STATUS_LINE.match(line):
            return line.strip()
    match = _STATUS_FIELD.search(text)
    if match:
        return match.group(0)
    return None


def declared_hosts(command: list[str]) -> list[str]:
    """Hostnames of URLs that appear in the server command line, in order.

    `--base-url https://api.example.com/v1` and `API_URL=https://x.example` both
    declare a host. Lowercased, without the port.
    """
    hosts: list[str] = []
    for token in command:
        for match in _URL_HOST.finditer(token):
            host = match.group(1).lower().strip("[]")
            if host not in hosts:
                hosts.append(host)
    return hosts


def warnings_for(result: RunResult) -> list[Warning]:
    """Compute every warning the brief asks for, in a stable order."""
    found: list[Warning] = []
    declared = declared_hosts(result.command)

    for tool in result.tools:
        if not tool.hosts:
            continue
        hint = (tool.annotations or {}).get("openWorldHint")
        if hint is False:
            found.append(
                Warning(
                    CODE_OPEN_WORLD,
                    tool.name,
                    f"declares openWorldHint false but reached {', '.join(tool.hosts)}",
                )
            )
        if declared:
            outside = [h for h in tool.hosts if h.rsplit(":", 1)[0] not in declared]
            if outside:
                found.append(
                    Warning(
                        CODE_OUTSIDE_BASE,
                        tool.name,
                        f"reached {', '.join(outside)}, outside the declared base URL host(s) "
                        f"{', '.join(declared)}",
                    )
                )

    for call in result.calls:
        if call.ok and not call.hosts and call.network_evidence:
            found.append(
                Warning(
                    CODE_PROXY_BYPASS,
                    call.tool,
                    f"result contains {call.network_evidence!r} but no proxied connection was "
                    "seen during the call; the server may ignore proxy variables",
                )
            )
    return found
