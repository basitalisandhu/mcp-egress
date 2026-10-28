"""Entry point of the mcp-egress composite action.

Reads the action inputs from INPUT_* environment variables, runs `mcp-egress run`,
writes the `out` and `new-hosts` outputs to $GITHUB_OUTPUT and exits with the tool's
exit code, so a new host still fails the step after the outputs are set. It never sets
a proxy variable itself; the tool does that for the server it starts.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


def build_argv(env: dict[str, str]) -> list[str]:
    command = shlex.split(env.get("INPUT_COMMAND", ""))
    if not command:
        raise SystemExit("mcp-egress action: the `command` input is required")
    out = env.get("INPUT_OUT") or "egress.json"
    argv = [env.get("MCP_EGRESS_BIN") or "mcp-egress", "run", "--out", out]
    if env.get("INPUT_CALLS"):
        argv += ["--calls", env["INPUT_CALLS"]]
    baseline = env.get("INPUT_BASELINE", "")
    if baseline:
        argv += ["--baseline", baseline]
    if env.get("INPUT_CHECK", "true").strip().lower() == "true":
        if not baseline:
            raise SystemExit("mcp-egress action: `check: true` needs a `baseline`")
        argv.append("--check")
    return [*argv, "--", *command]


def new_hosts(out: Path) -> list[str]:
    try:
        check = json.loads(out.read_text(encoding="utf-8")).get("check")
    except (OSError, ValueError, AttributeError):
        return []
    hosts = check.get("new_hosts") if isinstance(check, dict) else None
    return [h for h in hosts if isinstance(h, str)] if isinstance(hosts, list) else []


def main() -> int:
    env = dict(os.environ)
    argv = build_argv(env)
    print("+ " + shlex.join(argv), flush=True)
    code = subprocess.run(argv, check=False).returncode
    out = Path(env.get("INPUT_OUT") or "egress.json")
    output_file = env.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as fh:
            fh.write(f"out={out}\n")
            fh.write(f"new-hosts={','.join(new_hosts(out))}\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
