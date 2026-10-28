"""Baseline files: load one, compare the hosts of a run against it."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .jsonfile import JsonFileError, read_json
from .recorder import host_key


class BaselineError(Exception):
    """The baseline file is missing or not a document this tool wrote."""


def load_baseline(path: Path) -> dict:
    try:
        data = read_json(path)
    except FileNotFoundError:
        raise BaselineError(f"baseline {path} does not exist") from None
    except JsonFileError as exc:
        raise BaselineError(f"baseline {exc}") from None
    except OSError as exc:
        raise BaselineError(f"cannot read baseline {path}: {exc.strerror or exc}") from None
    if not isinstance(data, dict) or not isinstance(data.get("hosts"), list):
        raise BaselineError(f"baseline {path} has no 'hosts' list")
    try:
        document_host_keys(data)
    except BaselineError as exc:
        raise BaselineError(f"baseline {path}: {exc}") from None
    return data


def document_host_keys(doc: dict) -> list[str]:
    """Distinct `host:port` keys of a document, in order."""
    # A dict keeps first-seen order with constant-time membership; a list made this
    # quadratic in the number of hosts.
    keys: dict[str, None] = {}
    for entry in doc.get("hosts", []):
        if not isinstance(entry, dict) or "host" not in entry or "port" not in entry:
            raise BaselineError("a hosts entry lacks host or port")
        port = entry["port"]
        if isinstance(port, bool) or not isinstance(port, int | str):
            raise BaselineError(f"a hosts entry has a bad port {port!r}")
        try:
            port = int(port)
        except ValueError:
            raise BaselineError(f"a hosts entry has a bad port {port!r}") from None
        keys.setdefault(host_key(str(entry["host"]).lower(), port), None)
    return list(keys)


@dataclass
class Comparison:
    baseline: str
    new_hosts: list[str] = field(default_factory=list)
    missing_hosts: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.new_hosts

    def to_dict(self) -> dict:
        return {
            "baseline": self.baseline,
            "ok": self.ok,
            "new_hosts": list(self.new_hosts),
            "missing_hosts": list(self.missing_hosts),
        }


def compare(current: dict, baseline: dict, baseline_name: str) -> Comparison:
    """Hosts in `current` that the baseline lacks, and the other way round."""
    now = document_host_keys(current)
    then = document_host_keys(baseline)
    now_set, then_set = set(now), set(then)
    return Comparison(
        baseline=baseline_name,
        new_hosts=[k for k in now if k not in then_set],
        missing_hosts=[k for k in then if k not in now_set],
    )


def tools_reaching(doc: dict, key: str) -> list[str]:
    """Names of the tools in `doc` whose host list contains `key`."""
    return [t["name"] for t in doc.get("tools", []) if key in t.get("hosts", [])]


@dataclass
class DocumentDiff:
    comparison: Comparison
    added_hosts: dict[str, list[str]]
    removed_hosts: dict[str, list[str]]
    changed_tools: dict[str, Comparison]


def _tool_documents(doc: dict) -> dict[str, dict]:
    """Aggregate repeated tool names while normalising keys as compare() does."""
    tools = doc.get("tools", [])
    if not isinstance(tools, list):
        raise BaselineError("'tools' must be a list")
    result: dict[str, dict] = {}
    for tool in tools:
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
            raise BaselineError("a tools entry lacks a string name")
        hosts = tool.get("hosts", [])
        if not isinstance(hosts, list) or not all(isinstance(host, str) for host in hosts):
            raise BaselineError("a tool's hosts must be a list of host:port strings")
        target = result.setdefault(tool["name"], {"hosts": []})
        for key in hosts:
            try:
                host, port = key.rsplit(":", 1)
                port_number = int(port)
                if not host:
                    raise ValueError
            except ValueError:
                raise BaselineError(f"bad tool host key {key!r}") from None
            target["hosts"].append({"host": host, "port": port_number})
    return result


def diff_documents(old: dict, new: dict, baseline_name: str) -> DocumentDiff:
    """Compare saved documents without running a server or modifying either file."""
    comparison = compare(new, old, baseline_name)
    before = _tool_documents(old)
    after = _tool_documents(new)
    changed: dict[str, Comparison] = {}
    for name in dict.fromkeys([*before, *after]):
        change = compare(
            after.get(name, {"hosts": []}), before.get(name, {"hosts": []}), baseline_name
        )
        if change.new_hosts or change.missing_hosts:
            changed[name] = change

    def attribution(keys: list[str], tools: dict[str, dict]) -> dict[str, list[str]]:
        tool_keys = {name: set(document_host_keys(doc)) for name, doc in tools.items()}
        return {key: [name for name, hosts in tool_keys.items() if key in hosts] for key in keys}

    return DocumentDiff(
        comparison,
        attribution(comparison.new_hosts, after),
        attribution(comparison.missing_hosts, before),
        changed,
    )


def render_diff(result: DocumentDiff) -> str:
    lines: list[str] = []
    for label, hosts in (
        ("added hosts", result.added_hosts),
        ("removed hosts", result.removed_hosts),
    ):
        lines.append(f"{label} ({len(hosts)}):")
        for host, tools in hosts.items():
            note = "tools: " + ", ".join(tools) if tools else "no tool attribution"
            lines.append(f"  {host}  ({note})")
        if not hosts:
            lines.append("  (none)")
    lines.append(f"changed tools ({len(result.changed_tools)}):")
    for name, change in result.changed_tools.items():
        lines.append(f"  {name}")
        lines.append("    added: " + (", ".join(change.new_hosts) or "(none)"))
        lines.append("    removed: " + (", ".join(change.missing_hosts) or "(none)"))
    if not result.changed_tools:
        lines.append("  (none)")
    return "\n".join(lines)
