# Contributing

Thanks for considering a contribution. The project is small on purpose: a recording proxy, a runner around the official `mcp` client, a few heuristics and a report. Most useful contributions are better heuristics, more ways to capture traffic, and fixture servers that behave like real ones.

## Set up

Requires Python 3.11 or newer and [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/basitalisandhu/mcp-egress
cd mcp-egress
uv venv
uv pip install -e ".[dev]"
uv run pytest -q
```

Without uv:

```bash
python3 -m venv .venv && . .venv/bin/activate
python3 -m pip install -e ".[dev]"
python3 -m pytest -q
```

## Before you open a pull request

```bash
make check          # ruff check, ruff format --check, pytest
make build          # uv build
```

CI runs the same commands on Python 3.11 and 3.12 on Ubuntu and macOS, then builds the wheel and runs `mcp-egress --version` from it.

## Layout

| Path | Role |
|---|---|
| `src/mcp_egress/proxy.py` | The asyncio `CONNECT` and absolute-form proxy. Records hosts, never payloads. |
| `src/mcp_egress/recorder.py` | Connection records and the phase and tool context they are attributed to. |
| `src/mcp_egress/runner.py` | Spawns the server with the proxy environment and drives it with the `mcp` client. |
| `src/mcp_egress/analysis.py` | Declared base URLs, network-shaped output, the three warnings. |
| `src/mcp_egress/baseline.py` | Baseline loading and comparison. |
| `src/mcp_egress/report.py` | The `egress.json` document and the terminal report. |
| `src/mcp_egress/cli.py` | Argument parsing and exit codes. |
| `schema/egress.schema.json` | JSON Schema of the output; tests validate every run against it. |
| `tests/fixtures/` | Two MCP servers: `proxied_server.py` honours proxy variables, `socket_server.py` does not. |

## Tests

Tests use a local HTTP server on 127.0.0.1 and the two fixture servers; nothing reaches the internet. The runner sets the child's proxy variables explicitly and clears `NO_PROXY`, so the suite passes whether or not the machine running it sits behind a corporate or sandbox proxy. If you add a tool to a fixture server, keep it deterministic and keep its docstring, which is what `tools/list` reports.

When you change the output document, update `schema/egress.schema.json` and the table in the README together; `tests/test_run.py::test_output_document_matches_the_schema` will fail until they agree.

## Style

- `ruff` formats and lints; line length 100.
- Standard library plus `mcp` at runtime. New runtime dependencies need a reason in the pull request.
- No model names or vendor identifiers in the repository.
- Plain language in messages: say what was seen and what it probably means. Warnings are hints; name them that way.
- The proxy must keep binding 127.0.0.1 only and must keep recording hosts, not payloads. Changes to either need a SECURITY.md update in the same pull request.

## Reporting security issues

See [SECURITY.md](SECURITY.md).
