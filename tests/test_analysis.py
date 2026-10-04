"""Heuristics: network-shaped output, declared base URLs and the warnings built from a run."""

from __future__ import annotations

import pytest

from mcp_egress.analysis import (
    CODE_OPEN_WORLD,
    CODE_OUTSIDE_BASE,
    CODE_PROXY_BYPASS,
    declared_hosts,
    network_evidence,
    warnings_for,
)
from mcp_egress.recorder import Recorder
from mcp_egress.runner import CallOutcome, RunResult, ToolInfo


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("see https://api.example.com/v1/items for details", "https://api.example.com/v1/items"),
        ("200 OK\nhello", "200 OK"),
        ("HTTP/1.1 404 Not Found", "HTTP/1.1 404 Not Found"),
        ('{"status": 503, "body": ""}', 'status": 503'),
        ("status_code=301", "status_code=301"),
    ],
)
def test_network_evidence_detects_urls_status_lines_and_status_fields(text, expected):
    assert network_evidence(text) == expected


@pytest.mark.parametrize(
    "text",
    ["all quiet", "the answer is 42", "version 2.0.1 released in 2026", "", "status: pending"],
)
def test_network_evidence_ignores_plain_text(text):
    assert network_evidence(text) is None


def test_network_evidence_ignores_the_proxy_url_but_not_others():
    proxy = "http://127.0.0.1:41065"
    assert network_evidence(f'{{"HTTP_PROXY": "{proxy}"}}', (proxy,)) is None
    assert (
        network_evidence(f"{proxy} and http://other.example/", (proxy,)) == "http://other.example/"
    )


def test_declared_hosts_come_from_urls_in_the_command_line():
    cmd = [
        "uvx",
        "some-server",
        "--base-url",
        "https://api.example.com/v1",
        "API_URL=http://user:pw@second.example:8080/x",
        "--verbose",
        "https://API.example.com/other",
    ]
    assert declared_hosts(cmd) == ["api.example.com", "second.example"]
    assert declared_hosts(["python", "server.py"]) == []


def _result(command, tools, calls):
    return RunResult(
        command=command,
        started="2026-10-03T00:00:00Z",
        finished="2026-10-03T00:00:01Z",
        proxy_url="http://127.0.0.1:1",
        server=None,
        tools=tools,
        calls=calls,
        recorder=Recorder(),
    )


def _call(tool, ok=True, hosts=(), evidence=None):
    return CallOutcome(
        tool=tool,
        arguments={},
        ok=ok,
        is_error=not ok,
        error=None if ok else "boom",
        text="",
        hosts=list(hosts),
        network_evidence=evidence,
        duration_ms=1,
    )


def test_open_world_false_tool_that_reached_a_host_is_flagged():
    tools = [
        ToolInfo("ping", None, None, {"openWorldHint": False}, ["a.example:443"]),
        ToolInfo("fetch", None, None, {"openWorldHint": True}, ["a.example:443"]),
        ToolInfo("echo", None, None, {"openWorldHint": False}, []),
        ToolInfo("bare", None, None, None, ["a.example:443"]),
    ]
    found = warnings_for(_result(["srv"], tools, []))
    assert [(w.code, w.tool) for w in found] == [(CODE_OPEN_WORLD, "ping")]
    assert "a.example:443" in found[0].message


def test_tools_outside_declared_base_url_are_flagged_only_when_one_is_declared():
    tools = [
        ToolInfo("fetch", None, None, None, ["cdn.example:443", "api.example:443"]),
        ToolInfo("search", None, None, None, ["api.example:443"]),
    ]
    found = warnings_for(_result(["srv", "--base-url", "https://api.example/"], tools, []))
    assert [(w.code, w.tool) for w in found] == [(CODE_OUTSIDE_BASE, "fetch")]
    assert (
        "cdn.example:443" in found[0].message
        and "api.example:443" not in found[0].message.split(",")[0]
    )
    assert warnings_for(_result(["srv"], tools, [])) == []


def test_possible_proxy_bypass_needs_success_evidence_and_no_connections():
    calls = [
        _call("fetch", ok=True, hosts=[], evidence="200 OK"),
        _call("proxied", ok=True, hosts=["a.example:80"], evidence="200 OK"),
        _call("quiet", ok=True, hosts=[], evidence=None),
        _call("failed", ok=False, hosts=[], evidence="200 OK"),
    ]
    found = warnings_for(_result(["srv"], [], calls))
    assert [(w.code, w.tool) for w in found] == [(CODE_PROXY_BYPASS, "fetch")]
    assert "'200 OK'" in found[0].message
