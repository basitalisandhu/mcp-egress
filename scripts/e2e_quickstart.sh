#!/usr/bin/env bash
# Run the README quick start on a fresh install, with no network beyond loopback.
#
# Installs this checkout into a new virtual environment in a temporary directory (the
# same as `pipx install git+...`), starts a local web server on port 39211 to stand in
# for an API, and runs the quick start against the fixture MCP server: record a
# baseline, check it (exit 0), then check a run that reaches a new host (exit 1).
# Finally it diffs the two saved documents.
#
#   scripts/e2e_quickstart.sh            # uses python3
#   PYTHON=python3.12 scripts/e2e_quickstart.sh
set -euo pipefail

PYTHON="${PYTHON:-python3}"
PORT="${PORT:-39211}"
repo="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
web_pid=""
cleanup() {
  if [ -n "$web_pid" ]; then kill "$web_pid" 2>/dev/null || true; fi
  rm -rf "$work"
}
trap cleanup EXIT

"$PYTHON" -m venv "$work/venv"
"$work/venv/bin/python" -m pip install --quiet --disable-pip-version-check "$repo"
bin="$work/venv/bin/mcp-egress"
py="$work/venv/bin/python"
"$bin" --version

mkdir "$work/site" "$work/run"
echo ok >"$work/site/index.html"
"$py" -m http.server "$PORT" --bind 127.0.0.1 --directory "$work/site" >/dev/null 2>&1 &
web_pid=$!
for _ in $(seq 1 50); do
  if "$py" -c "import socket; socket.create_connection(('127.0.0.1', $PORT), 0.2)" 2>/dev/null; then break; fi
  sleep 0.1
done
kill -0 "$web_pid" 2>/dev/null || { echo "FAIL: the local web server did not start on port $PORT" >&2; exit 1; }

cd "$work/run"
cp "$repo/tests/fixtures/proxied_server.py" server.py
url="http://127.0.0.1:$PORT/"
printf '[{"tool": "fetch", "arguments": {"url": "%s"}}, {"tool": "ping", "arguments": {"url": "%s"}}, {"tool": "echo", "arguments": {"text": "no network"}}]\n' "$url" "$url" >calls.json
printf '[{"tool": "echo", "arguments": {"text": "no network"}}]\n' >quiet.json

expect() { # expect <file> <text>
  if ! grep -qF -- "$2" "$1"; then
    echo "FAIL: expected to find: $2" >&2
    cat "$1" >&2
    exit 1
  fi
}
run() { # run <expected exit code> <output file> <args...>
  local want="$1" out="$2"
  shift 2
  set +e
  "$bin" "$@" >"$out" 2>"$out.err"
  local got=$?
  set -e
  if [ "$got" != "$want" ]; then
    echo "FAIL: mcp-egress $* exited $got, expected $want" >&2
    cat "$out" "$out.err" >&2
    exit 1
  fi
}

# Quick start, line 2: record once.
run 0 record.txt run --calls calls.json --baseline egress.baseline.json -- "$py" server.py
expect record.txt "127.0.0.1  $PORT  http    call:fetch  fetch, ping  2"
expect record.txt '"WebFetch(domain:127.0.0.1)",'
expect record.txt "open-world-hint-false      ping: declares openWorldHint false but reached 127.0.0.1:$PORT"
test -s egress.baseline.json

# Quick start, line 3: in CI, the same run passes the check.
run 0 check.txt run --calls calls.json --baseline egress.baseline.json --check -- "$py" server.py

# A baseline without the host, then the check fails on the new host.
run 0 quiet.txt run --calls quiet.json --baseline quiet.baseline.json -- "$py" server.py
run 1 new.txt run --calls calls.json --baseline quiet.baseline.json --check --out new.json -- "$py" server.py
expect new.txt "127.0.0.1:$PORT"

# Compare the saved documents without running the server.
run 1 diff.txt diff quiet.baseline.json new.json
expect diff.txt "added hosts (1):"

echo "quick start OK on a fresh install"
