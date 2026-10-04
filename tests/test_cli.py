"""The command line: exit codes, baseline save and check, output file, paste blocks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from mcp_egress import __version__
from mcp_egress.cli import EXIT_NEW_HOSTS, EXIT_OK, EXIT_SERVER, EXIT_USAGE, main, split_command

SCHEMA = json.loads((Path(__file__).parent.parent / "schema" / "egress.schema.json").read_text())


def _calls_file(tmp_path: Path, url: str) -> str:
    path = tmp_path / "calls.json"
    path.write_text(json.dumps([{"tool": "fetch", "arguments": {"url": url}}]))
    return str(path)


def _run(tmp_path: Path, command: list[str], *options: str) -> int:
    argv = ["run", "--server-stderr", str(tmp_path / "server.log"), *options, "--", *command]
    return main(argv)


def test_split_command_at_the_first_double_dash():
    assert split_command(["run", "--calls", "c.json", "--", "python", "s.py", "--", "x"]) == (
        ["run", "--calls", "c.json"],
        ["python", "s.py", "--", "x"],
    )
    assert split_command(["run", "python", "s.py"]) == (["run", "python", "s.py"], [])


def test_usage_errors_exit_2(tmp_path):
    assert main([]) == EXIT_USAGE
    with pytest.raises(SystemExit) as exc:
        main(["run"])
    assert exc.value.code == EXIT_USAGE
    with pytest.raises(SystemExit) as exc:
        main(["run", "--check", "--", "python", "s.py"])
    assert exc.value.code == EXIT_USAGE
    missing = str(tmp_path / "missing-baseline.json")
    assert (
        _run(tmp_path, [sys.executable, "-c", "pass"], "--check", "--baseline", missing)
        == EXIT_USAGE
    )
    bad_calls = tmp_path / "bad.json"
    bad_calls.write_text("[1]")
    assert _run(tmp_path, [sys.executable, "-c", "pass"], "--calls", str(bad_calls)) == EXIT_USAGE


def test_server_that_cannot_start_exits_3(tmp_path, capsys):
    out = str(tmp_path / "egress.json")
    assert _run(tmp_path, [str(tmp_path / "no-such-server")], "--out", out) == EXIT_SERVER
    assert "cannot start" in capsys.readouterr().err
    assert not Path(out).exists()


def test_run_writes_the_document_and_prints_table_and_blocks(
    tmp_path, proxied_command, http_server, capsys
):
    out = tmp_path / "egress.json"
    code = _run(
        tmp_path,
        proxied_command,
        "--calls",
        _calls_file(tmp_path, http_server.url),
        "--out",
        str(out),
    )
    assert code == EXIT_OK
    text = capsys.readouterr().out
    assert "server: proxied-fixture" in text
    assert f"127.0.0.1  {http_server.port}" in text
    assert '"WebFetch(domain:127.0.0.1)",' in text
    assert "Sandbox allowed domains" in text
    assert f"Wrote {out}" in text
    doc = json.loads(out.read_text())
    jsonschema.validate(doc, SCHEMA)
    assert [h["port"] for h in doc["hosts"]] == [http_server.port]
    assert doc["tools"][0]["name"] == "fetch" and doc["tools"][0]["hosts"] == [http_server.key]


def test_baseline_without_check_saves_the_baseline(tmp_path, proxied_command, http_server, capsys):
    baseline = tmp_path / "baseline.json"
    out = tmp_path / "egress.json"
    code = _run(
        tmp_path,
        proxied_command,
        "--calls",
        _calls_file(tmp_path, http_server.url),
        "--out",
        str(out),
        "--baseline",
        str(baseline),
    )
    assert code == EXIT_OK
    assert f"Baseline saved to {baseline}" in capsys.readouterr().out
    assert json.loads(baseline.read_text())["hosts"] == json.loads(out.read_text())["hosts"]


def test_check_exits_1_and_lists_new_hosts(tmp_path, proxied_command, http_server, capsys):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"hosts": [{"host": "api.example", "port": 443}], "tools": []}))
    out = tmp_path / "egress.json"
    code = _run(
        tmp_path,
        proxied_command,
        "--calls",
        _calls_file(tmp_path, http_server.url),
        "--out",
        str(out),
        "--baseline",
        str(baseline),
        "--check",
    )
    assert code == EXIT_NEW_HOSTS
    text = capsys.readouterr().out
    assert "1 new host(s)" in text
    assert f"  {http_server.key}  (tools: fetch)" in text
    doc = json.loads(out.read_text())
    jsonschema.validate(doc, SCHEMA)
    assert doc["check"] == {
        "baseline": str(baseline),
        "ok": False,
        "new_hosts": [http_server.key],
        "missing_hosts": ["api.example:443"],
    }
    # The baseline itself is untouched by a check.
    assert json.loads(baseline.read_text())["hosts"][0]["host"] == "api.example"


def test_check_exits_0_when_every_host_is_in_the_baseline(
    tmp_path, proxied_command, http_server, capsys
):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"hosts": [{"host": "127.0.0.1", "port": http_server.port}]}))
    out = tmp_path / "egress.json"
    code = _run(
        tmp_path,
        proxied_command,
        "--calls",
        _calls_file(tmp_path, http_server.url),
        "--out",
        str(out),
        "--baseline",
        str(baseline),
        "--check",
    )
    assert code == EXIT_OK
    assert "no new hosts" in capsys.readouterr().out
    assert json.loads(out.read_text())["check"]["ok"] is True


def test_check_does_not_overwrite_a_baseline_at_the_default_out_path(
    tmp_path, proxied_command, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    baseline = tmp_path / "egress.json"
    baseline.write_text(json.dumps({"hosts": [], "marker": True}))
    code = _run(tmp_path, proxied_command, "--baseline", "egress.json", "--check")
    assert code == EXIT_OK
    assert "Not overwriting baseline" in capsys.readouterr().out
    assert json.loads(baseline.read_text()) == {"hosts": [], "marker": True}


def test_version_flag():
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_module_and_console_entry_points(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "mcp_egress", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == f"mcp-egress {__version__}"
    script = Path(sys.executable).with_name("mcp-egress")
    if script.exists():
        result = subprocess.run(
            [str(script), "run", "--help"], capture_output=True, text=True, check=True
        )
        assert "--baseline" in result.stdout and "--check" in result.stdout
