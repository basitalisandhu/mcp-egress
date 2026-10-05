"""The format_version 1 schema accepts recordings with and without host addresses."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema

SCHEMA = json.loads((Path(__file__).parent.parent / "schema" / "egress.schema.json").read_text())

HOST = {
    "host": "api.example",
    "port": 443,
    "scheme": "https",
    "phase": "call",
    "tool": "fetch",
    "first_seen": "2026-10-01T10:00:00Z",
    "bytes_out": 10,
    "bytes_in": 20,
    "connections": 1,
    "phases": ["call"],
    "tools": ["fetch"],
}


def _doc(host):
    return {
        "format_version": 1,
        "generator": {"name": "mcp-egress", "version": "0.1.0"},
        "command": ["python", "server.py"],
        "started": "2026-10-01T10:00:00Z",
        "finished": "2026-10-01T10:00:05Z",
        "proxy": "http://127.0.0.1:54321",
        "server": None,
        "hosts": [host],
        "tools": [],
        "calls": [],
        "warnings": [],
        "check": None,
    }


def test_recording_without_addresses_still_validates():
    host = copy.deepcopy(HOST)
    assert "addresses" not in host
    jsonschema.validate(_doc(host), SCHEMA)


def test_recording_with_addresses_validates():
    host = {**HOST, "addresses": ["93.184.216.34", "2606:2800:220:1::1"]}
    jsonschema.validate(_doc(host), SCHEMA)
    jsonschema.validate(_doc({**HOST, "addresses": []}), SCHEMA)


def test_addresses_must_still_be_a_list_of_distinct_strings():
    for bad in ("1.2.3.4", [1], ["1.2.3.4", "1.2.3.4"]):
        try:
            jsonschema.validate(_doc({**HOST, "addresses": bad}), SCHEMA)
        except jsonschema.ValidationError:
            continue
        raise AssertionError(f"addresses={bad!r} should not validate")
