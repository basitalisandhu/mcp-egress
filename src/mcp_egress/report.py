"""The egress.json document and the human-readable report."""

from __future__ import annotations

import json
from pathlib import Path

from . import __version__
from .analysis import Warning
from .baseline import Comparison, tools_reaching
from .runner import RunResult

FORMAT_VERSION = 1


def build_document(result: RunResult, warnings: list[Warning]) -> dict:
    """The JSON document written to `--out` (and used as a baseline)."""
    return {
        "format_version": FORMAT_VERSION,
        "generator": {"name": "mcp-egress", "version": __version__},
        "command": list(result.command),
        "started": result.started,
        "finished": result.finished,
        "proxy": result.proxy_url,
        "server": result.server.to_dict() if result.server else None,
        "hosts": [h.to_dict() for h in result.recorder.hosts()],
        "tools": [t.to_dict() for t in result.tools],
        "calls": [c.to_dict() for c in result.calls],
        "warnings": [w.to_dict() for w in warnings],
        "check": None,
    }


def write_document(doc: dict, path: Path) -> None:
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} kB"
    return f"{n / (1024 * 1024):.1f} MB"


def _table(rows: list[list[str]], headers: list[str]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    lines = [fmt.format(*headers).rstrip()]
    lines.extend(fmt.format(*row).rstrip() for row in rows)
    return "\n".join(lines)


def render_hosts_table(doc: dict) -> str:
    hosts = doc["hosts"]
    if not hosts:
        return "No proxied connections were seen."
    rows = []
    for h in hosts:
        first = h["phase"] if not h["tool"] else f"{h['phase']}:{h['tool']}"
        tools = ", ".join(h["tools"]) or "-"
        rows.append(
            [
                h["host"],
                str(h["port"]),
                h["scheme"],
                first,
                tools,
                str(h["connections"]),
                _fmt_bytes(h["bytes_out"]),
                _fmt_bytes(h["bytes_in"]),
            ]
        )
    headers = ["HOST", "PORT", "SCHEME", "FIRST SEEN", "TOOLS", "CONNS", "OUT", "IN"]
    return _table(rows, headers)


def domains(doc: dict) -> list[str]:
    """Distinct hostnames in first-seen order, without ports."""
    seen: list[str] = []
    for h in doc["hosts"]:
        if h["host"] not in seen:
            seen.append(h["host"])
    return seen


def render_claude_code_rules(doc: dict) -> str:
    """Ready to paste into `permissions.allow` of a Claude Code settings file."""
    names = domains(doc)
    if not names:
        return "# no hosts seen, nothing to allow"
    return "\n".join(f'"WebFetch(domain:{name})",' for name in names)


def render_sandbox_domains(doc: dict) -> str:
    """Ready to paste as a sandbox allowed-domain list (a JSON array of hosts)."""
    names = domains(doc)
    return json.dumps(names, indent=2)


def render_warnings(doc: dict) -> str:
    if not doc["warnings"]:
        return "No warnings."
    lines = []
    for w in doc["warnings"]:
        who = f"{w['tool']}: " if w["tool"] else ""
        lines.append(f"  {w['code']:<26} {who}{w['message']}")
    return "Warnings:\n" + "\n".join(lines)


def render_check(doc: dict, comparison: Comparison) -> str:
    if comparison.ok:
        extra = ""
        if comparison.missing_hosts:
            extra = f" ({len(comparison.missing_hosts)} baseline host(s) not seen this run)"
        return f"Baseline {comparison.baseline}: no new hosts{extra}."
    lines = [f"Baseline {comparison.baseline}: {len(comparison.new_hosts)} new host(s):"]
    for key in comparison.new_hosts:
        tools = tools_reaching(doc, key)
        suffix = f"  (tools: {', '.join(tools)})" if tools else "  (no tool, seen while listing)"
        lines.append(f"  {key}{suffix}")
    return "\n".join(lines)


def render_report(doc: dict) -> str:
    """The full terminal report: summary, table, paste blocks, warnings."""
    server = doc["server"]
    server_line = (
        f"server: {server['name']} {server['version']} (protocol {server['protocol_version']})"
        if server
        else "server: unknown"
    )
    summary = (
        f"{server_line}, {len(doc['tools'])} tool(s), {len(doc['calls'])} call(s), "
        f"{len(doc['hosts'])} host(s)"
    )
    parts = [
        "mcp-egress: " + " ".join(doc["command"]),
        summary,
        "",
        render_hosts_table(doc),
        "",
        "Claude Code permission rules (settings.json, permissions.allow):",
        render_claude_code_rules(doc),
        "",
        "Sandbox allowed domains (settings.json, sandbox.network.allowedDomains):",
        render_sandbox_domains(doc),
        "",
        render_warnings(doc),
    ]
    return "\n".join(parts)
