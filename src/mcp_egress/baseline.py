"""Baseline files: load one, compare the hosts of a run against it."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .recorder import host_key


class BaselineError(Exception):
    """The baseline file is missing or not a document this tool wrote."""


def load_baseline(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise BaselineError(f"baseline {path} does not exist") from None
    except (OSError, ValueError) as exc:
        raise BaselineError(f"cannot read baseline {path}: {exc}") from None
    if not isinstance(data, dict) or not isinstance(data.get("hosts"), list):
        raise BaselineError(f"baseline {path} has no 'hosts' list")
    return data


def document_host_keys(doc: dict) -> list[str]:
    """Distinct `host:port` keys of a document, in order."""
    keys: list[str] = []
    for entry in doc.get("hosts", []):
        if not isinstance(entry, dict) or "host" not in entry or "port" not in entry:
            raise BaselineError("a hosts entry lacks host or port")
        key = host_key(str(entry["host"]).lower(), int(entry["port"]))
        if key not in keys:
            keys.append(key)
    return keys


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
    return Comparison(
        baseline=baseline_name,
        new_hosts=[k for k in now if k not in then],
        missing_hosts=[k for k in then if k not in now],
    )


def tools_reaching(doc: dict, key: str) -> list[str]:
    """Names of the tools in `doc` whose host list contains `key`."""
    return [t["name"] for t in doc.get("tools", []) if key in t.get("hosts", [])]
