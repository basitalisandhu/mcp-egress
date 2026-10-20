"""Heuristics over a run: declared base URLs, network-shaped output, warnings."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runner import RunResult, ToolInfo

CODE_PROXY_BYPASS = "possible-proxy-bypass"
CODE_OPEN_WORLD = "open-world-hint-false"
CODE_OUTSIDE_BASE = "outside-declared-base-url"
CODE_HIDDEN_CHARACTERS = "hidden-characters"

# Code points listed by name in a hidden-characters message before it says "and N more".
_HIDDEN_LISTED = 5
# Longest decoded tag-character text quoted in a message.
_TAG_TEXT_MAX = 80

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


def _is_hidden(char: str) -> bool:
    # Format characters (category Cf) render as nothing: zero-width spaces and
    # joiners, bidi embeddings, overrides and isolates, the byte order mark, the
    # soft hyphen and the tag block U+E0000 to U+E007F that can spell out ASCII.
    # Variation selectors supplement (U+E0100 to U+E01EF) carries data the same way.
    return unicodedata.category(char) == "Cf" or 0xE0100 <= ord(char) <= 0xE01EF


def hidden_characters(text: str) -> list[str]:
    """Every invisible or bidi-control character in `text`, in order, repeats kept."""
    return [char for char in text if _is_hidden(char)]


def _tag_text(chars: list[str]) -> str:
    # Tag characters U+E0020 to U+E007E mirror printable ASCII one to one.
    return "".join(chr(ord(c) - 0xE0000) for c in chars if 0xE0020 <= ord(c) <= 0xE007E)


def _describe_hidden(field: str, chars: list[str]) -> str:
    distinct = list(dict.fromkeys(chars))
    named = [f"U+{ord(c):04X} {unicodedata.name(c, 'UNNAMED')}" for c in distinct[:_HIDDEN_LISTED]]
    if len(distinct) > _HIDDEN_LISTED:
        named.append(f"and {len(distinct) - _HIDDEN_LISTED} more")
    message = (
        f"{field} contains {len(chars)} invisible or bidi-control character(s): {', '.join(named)}"
    )
    tags = _tag_text(chars)
    if tags:
        shown = tags if len(tags) <= _TAG_TEXT_MAX else tags[:_TAG_TEXT_MAX] + "..."
        message += f"; tag characters decode to {shown!r}"
    return message


def _hidden_character_warnings(tool: ToolInfo) -> list[Warning]:
    found: list[Warning] = []
    for field in ("name", "title", "description"):
        chars = hidden_characters(getattr(tool, field) or "")
        if chars:
            found.append(Warning(CODE_HIDDEN_CHARACTERS, tool.name, _describe_hidden(field, chars)))
    return found


def warnings_for(result: RunResult) -> list[Warning]:
    """Compute every warning the brief asks for, in a stable order."""
    found: list[Warning] = []
    declared = declared_hosts(result.command)

    for tool in result.tools:
        found.extend(_hidden_character_warnings(tool))
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
