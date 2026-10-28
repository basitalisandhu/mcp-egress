"""The composite action's runner (action/run.py): arguments, outputs and exit code."""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from .conftest import PROXIED_SERVER

RUN_PY = Path(__file__).parent.parent / "action" / "run.py"
spec = importlib.util.spec_from_file_location("action_run", RUN_PY)
assert spec and spec.loader
action_run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(action_run)


def test_build_argv_defaults_check_against_the_baseline() -> None:
    argv = action_run.build_argv(
        {"INPUT_COMMAND": "uvx 'some server' --flag", "INPUT_CHECK": "true"}
        | {"INPUT_BASELINE": "b.json"}
    )
    assert argv == [
        "mcp-egress",
        "run",
        "--out",
        "egress.json",
        "--baseline",
        "b.json",
        "--check",
        "--",
        "uvx",
        "some server",
        "--flag",
    ]


def test_build_argv_records_when_check_is_false() -> None:
    argv = action_run.build_argv(
        {
            "INPUT_COMMAND": "python s.py",
            "INPUT_CHECK": "false",
            "INPUT_BASELINE": "b.json",
            "INPUT_CALLS": "c.json",
            "INPUT_OUT": "o.json",
        }
    )
    assert argv == [
        "mcp-egress",
        "run",
        "--out",
        "o.json",
        "--calls",
        "c.json",
        "--baseline",
        "b.json",
        "--",
        "python",
        "s.py",
    ]


@pytest.mark.parametrize(
    "env, message",
    [
        ({"INPUT_COMMAND": "  "}, "`command` input is required"),
        ({"INPUT_COMMAND": "x", "INPUT_CHECK": "true", "INPUT_BASELINE": ""}, "needs a `baseline`"),
    ],
)
def test_build_argv_errors(env, message) -> None:
    with pytest.raises(SystemExit, match=message):
        action_run.build_argv(env)


def _run_action(tmp_path: Path, **inputs: str) -> tuple[int, dict[str, str]]:
    output = tmp_path / "github_output"
    output.write_text("")
    env = {
        **os.environ,
        "GITHUB_OUTPUT": str(output),
        "MCP_EGRESS_BIN": str(Path(sys.executable).parent / "mcp-egress"),
        **{f"INPUT_{k.upper()}": v for k, v in inputs.items()},
    }
    code = subprocess.run(
        [sys.executable, str(RUN_PY)], cwd=tmp_path, env=env, check=False
    ).returncode
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines() if "=" in line)
    return code, outputs


def test_action_records_then_fails_on_a_new_host(tmp_path, http_server) -> None:
    command = shlex.join([sys.executable, str(PROXIED_SERVER)])
    quiet = tmp_path / "quiet.json"
    quiet.write_text(json.dumps([{"tool": "echo", "arguments": {"text": "no network"}}]))
    code, outputs = _run_action(
        tmp_path, command=command, calls=str(quiet), check="false", baseline="egress.baseline.json"
    )
    assert code == 0
    assert outputs == {"out": "egress.json", "new-hosts": ""}
    assert (tmp_path / "egress.baseline.json").exists()

    fetch = tmp_path / "fetch.json"
    fetch.write_text(json.dumps([{"tool": "fetch", "arguments": {"url": http_server.url + "/"}}]))
    code, outputs = _run_action(
        tmp_path, command=command, calls=str(fetch), check="true", baseline="egress.baseline.json"
    )
    assert code == 1
    assert outputs["new-hosts"] == http_server.key
