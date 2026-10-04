"""End-to-end runs against the two fixture servers through the real mcp client."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import jsonschema
import pytest

from mcp_egress.analysis import CODE_OPEN_WORLD, CODE_OUTSIDE_BASE, CODE_PROXY_BYPASS, warnings_for
from mcp_egress.recorder import PHASE_CALL, PHASE_LIST
from mcp_egress.report import build_document, render_report
from mcp_egress.runner import CallSpec, RunError, child_environment, load_calls, run_server

SCHEMA = json.loads((Path(__file__).parent.parent / "schema" / "egress.schema.json").read_text())


def run(command, calls, server_log, timeout=20.0, startup_timeout=None):
    return asyncio.run(
        run_server(
            command, calls, timeout=timeout, errlog=server_log, startup_timeout=startup_timeout
        )
    )


def document(result):
    return build_document(result, warnings_for(result))


@pytest.fixture
def proxied_run(proxied_command, http_server, server_log, monkeypatch):
    monkeypatch.setenv("MCP_EGRESS_TEST_MARKER", "inherited")
    calls = [
        CallSpec("fetch", {"url": http_server.url + "/one"}),
        CallSpec("tunnel", {"url": http_server.url + "/two"}),
        CallSpec("ping", {"url": http_server.url + "/three"}),
        CallSpec("echo", {"text": "no network here"}),
        CallSpec("env"),
        CallSpec("missing_tool", {"x": 1}),
    ]
    result = run(proxied_command, calls, server_log)
    return result, document(result), http_server


def test_proxied_server_hosts_are_recorded_with_phase_and_tool(proxied_run):
    result, doc, server = proxied_run
    assert result.server is not None and result.server.name == "proxied-fixture"
    keys = {(h["host"], h["port"], h["scheme"]) for h in doc["hosts"]}
    assert keys == {("127.0.0.1", server.port, "http"), ("127.0.0.1", server.port, "https")}
    plain = next(h for h in doc["hosts"] if h["scheme"] == "http")
    assert plain["phase"] == PHASE_CALL and plain["tool"] == "fetch"
    assert plain["tools"] == ["fetch", "ping"] and plain["connections"] == 2
    assert plain["bytes_out"] > 0 and plain["bytes_in"] > 0
    tunnel = next(h for h in doc["hosts"] if h["scheme"] == "https")
    assert tunnel["tool"] == "tunnel" and tunnel["tools"] == ["tunnel"]
    assert sorted(server.requests) == [
        "GET /one HTTP/1.1",
        "GET /three HTTP/1.1",
        "GET /two HTTP/1.1",
    ]


def test_tools_section_carries_annotations_and_hosts(proxied_run):
    _, doc, server = proxied_run
    tools = {t["name"]: t for t in doc["tools"]}
    assert set(tools) == {"fetch", "ping", "tunnel", "echo", "env", "sleep"}
    assert tools["fetch"]["annotations"] == {"readOnlyHint": True, "openWorldHint": True}
    assert tools["fetch"]["hosts"] == [server.key]
    assert tools["tunnel"]["hosts"] == [server.key]
    assert tools["echo"]["hosts"] == []
    assert tools["fetch"]["description"].startswith("Fetch a URL")


def test_calls_section_records_outcomes(proxied_run):
    _, doc, server = proxied_run
    calls = {c["tool"]: c for c in doc["calls"]}
    assert calls["fetch"]["ok"] and calls["fetch"]["hosts"] == [server.key]
    assert calls["fetch"]["network_evidence"] == "200 OK"
    assert (
        calls["echo"]["ok"]
        and calls["echo"]["hosts"] == []
        and calls["echo"]["network_evidence"] is None
    )
    assert calls["missing_tool"]["ok"] is False
    assert "missing_tool" in (calls["missing_tool"]["error"] or "")
    assert all(c["duration_ms"] >= 0 for c in doc["calls"])


def test_child_gets_proxy_variables_and_inherits_the_rest(proxied_run):
    result, doc, _ = proxied_run
    env_call = next(c for c in result.calls if c.tool == "env")
    seen = json.loads(env_call.text)
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        assert seen[name] == result.proxy_url
    assert seen["NO_PROXY"] == "" and seen["no_proxy"] == ""
    assert seen["NODE_USE_ENV_PROXY"] == "1"
    assert seen["MCP_EGRESS_TEST_MARKER"] == "inherited"
    # Echoing the proxy address is not evidence of a bypass.
    assert not [w for w in doc["warnings"] if w["tool"] == "env"]


def test_child_environment_overrides_outer_proxy_settings():
    base = {"HTTPS_PROXY": "http://outer:1", "NO_PROXY": "localhost,127.0.0.1", "PATH": "/bin"}
    env = child_environment("http://127.0.0.1:5", base)
    assert env["HTTPS_PROXY"] == env["HTTP_PROXY"] == env["ALL_PROXY"] == "http://127.0.0.1:5"
    assert env["https_proxy"] == env["http_proxy"] == env["all_proxy"] == "http://127.0.0.1:5"
    assert env["NO_PROXY"] == "" and env["no_proxy"] == ""
    assert env["PATH"] == "/bin"
    assert "PATH" in child_environment("http://127.0.0.1:5")


def test_open_world_false_tool_is_flagged_and_proxied_calls_are_not(proxied_run):
    _, doc, _ = proxied_run
    codes = {(w["code"], w["tool"]) for w in doc["warnings"]}
    assert (CODE_OPEN_WORLD, "ping") in codes
    assert not [w for w in doc["warnings"] if w["code"] == CODE_PROXY_BYPASS]
    assert not [w for w in doc["warnings"] if w["code"] == CODE_OUTSIDE_BASE]


def test_output_document_matches_the_schema(proxied_run):
    _, doc, _ = proxied_run
    jsonschema.validate(doc, SCHEMA)
    assert doc["format_version"] == 1
    assert doc["generator"]["name"] == "mcp-egress"
    assert doc["command"][0] == sys.executable
    assert doc["check"] is None


def test_report_lists_hosts_tools_and_paste_blocks(proxied_run):
    _, doc, server = proxied_run
    text = render_report(doc)
    assert "127.0.0.1" in text and str(server.port) in text
    assert "fetch, ping" in text
    assert '"WebFetch(domain:127.0.0.1)",' in text
    assert "sandbox.network.allowedDomains" in text and '"127.0.0.1"' in text
    assert "open-world-hint-false" in text and "ping:" in text


def test_declared_base_url_on_the_command_line_flags_other_hosts(
    proxied_command, http_server, server_log
):
    command = [*proxied_command, "--base-url", "http://declared.example/"]
    result = run(command, [CallSpec("fetch", {"url": http_server.url})], server_log)
    found = [w for w in warnings_for(result) if w.code == CODE_OUTSIDE_BASE]
    assert [w.tool for w in found] == ["fetch"]
    assert "declared.example" in found[0].message and http_server.key in found[0].message


def test_socket_server_bypasses_the_proxy_and_is_warned_about(
    socket_command, http_server, server_log
):
    calls = [CallSpec("fetch", {"url": http_server.url + "/direct"}), CallSpec("quiet")]
    result = run(socket_command, calls, server_log)
    doc = document(result)
    jsonschema.validate(doc, SCHEMA)
    assert doc["hosts"] == []
    assert http_server.requests == ["GET /direct HTTP/1.1"], "the fixture really did go direct"
    fetch = next(c for c in doc["calls"] if c["tool"] == "fetch")
    assert fetch["ok"] and fetch["hosts"] == [] and fetch["network_evidence"] == "200 OK"
    assert [(w["code"], w["tool"]) for w in doc["warnings"]] == [(CODE_PROXY_BYPASS, "fetch")]
    assert "may ignore proxy variables" in render_report(doc)


def test_list_phase_without_calls(proxied_command, server_log):
    result = run(proxied_command, [], server_log)
    assert result.calls == [] and len(result.tools) == 6
    assert result.recorder.connections == []
    assert result.recorder.phase == "shutdown"
    assert PHASE_LIST not in {c.phase for c in result.recorder.connections}


def test_timed_out_call_is_recorded_not_raised(proxied_command, server_log):
    result = run(
        proxied_command,
        [CallSpec("sleep", {"seconds": 3})],
        server_log,
        timeout=0.5,
        startup_timeout=20,
    )
    call = result.calls[0]
    assert call.ok is False and call.error is not None
    assert "timed out" in call.error.lower()


def test_missing_command_raises_run_error(server_log, tmp_path):
    with pytest.raises(RunError, match="cannot start"):
        run([str(tmp_path / "does-not-exist")], [], server_log)


def test_server_that_exits_before_initialize_raises_run_error(server_log):
    with pytest.raises(RunError, match=r"initialize|list"):
        run([sys.executable, "-c", "import sys; sys.exit(3)"], [], server_log, timeout=5)


def test_load_calls_accepts_list_and_object_forms(tmp_path):
    as_list = tmp_path / "list.json"
    as_list.write_text(json.dumps([{"tool": "a", "arguments": {"x": 1}}, {"tool": "b"}]))
    calls = load_calls(str(as_list))
    assert [(c.tool, c.arguments) for c in calls] == [("a", {"x": 1}), ("b", {})]
    as_obj = tmp_path / "obj.json"
    as_obj.write_text(json.dumps({"calls": [{"tool": "c", "arguments": {}}]}))
    assert [c.tool for c in load_calls(str(as_obj))] == ["c"]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"arguments": {}}]))
    with pytest.raises(ValueError, match="needs a string 'tool'"):
        load_calls(str(bad))
    bad.write_text(json.dumps({"nope": 1}))
    with pytest.raises(ValueError, match="expected a list"):
        load_calls(str(bad))


def test_outer_proxy_in_the_test_environment_is_not_used(proxied_command, http_server, server_log):
    """Whatever HTTPS_PROXY or NO_PROXY say outside, the recording proxy sees the call."""
    result = run(proxied_command, [CallSpec("fetch", {"url": http_server.url})], server_log)
    assert [c.key for c in result.recorder.connections] == [http_server.key]
