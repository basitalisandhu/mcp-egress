# Good first issues

Issues the maintainer intends to open under the `good first issue` label, written out so
they can be filed in one sitting. Each is self-contained and has acceptance criteria that
`make check` can verify. Read [CONTRIBUTING.md](../CONTRIBUTING.md) first: `ruff` must
pass, the output document must keep matching `schema/egress.schema.json`, the proxy must
keep binding 127.0.0.1 only, and nothing in the tests may reach the internet.

## 1. Record the resolved IP addresses next to each host

**Context.** `hosts` entries carry the name the server asked for. Reviewers comparing a
baseline with a firewall log want the addresses the name resolved to at the time.

**Acceptance criteria.**

- `RecordingProxy` records, per connection, the address the upstream socket connected to
  (`writer.get_extra_info("peername")`), and `HostRecord.to_dict()` gains an
  `addresses` list of distinct IP strings in first-seen order. Failed connections add
  nothing.
- `schema/egress.schema.json` gains the field (array of strings, required) and the README
  table for `hosts` mentions it.
- Tests in `tests/test_proxy.py`: a `CONNECT` to the local HTTP server records
  `["127.0.0.1"]`; a 502 records `[]`.
- `--check` keeps comparing `host:port` only; addresses never cause a failure.

## 2. Add a `diff` subcommand for two documents

**Context.** `--check` compares a run with a baseline, but there is no way to compare two
saved documents without re-running the server, for example in a pull request that updates
the baseline.

**Acceptance criteria.**

- `mcp-egress diff OLD.json NEW.json` prints hosts added and removed (`host:port`, with the
  tools that reached them in `NEW` or `OLD`) and tools whose host list changed, and exits 1
  when any host was added, 0 otherwise, 2 when a file is unreadable or has no `hosts` list.
- Implemented in `src/mcp_egress/baseline.py` and `cli.py` with no new dependencies;
  `compare()` is reused, not duplicated.
- Tests in `tests/test_cli.py` cover added, removed and unchanged cases using hand-written
  documents, and the exit codes.
- README "Usage" gains a short section for the command.

## 3. Markdown report for pull request comments

**Context.** The terminal table is plain text. A Markdown rendering with the same content
can be posted as a pull request comment by a workflow step.

**Acceptance criteria.**

- `--format text|markdown` on `run` (default `text`). Markdown output has the hosts as a
  table (`host`, `port`, `scheme`, `first seen`, `tools`, `connections`, `bytes out`, `bytes
  in`), the two paste blocks as fenced code blocks, warnings as a list and, when `--check`
  ran, the new hosts as a list.
- Implemented as `render_report_markdown(doc)` in `src/mcp_egress/report.py`, sharing
  `domains()` and the warning text with the text renderer.
- Tests in `tests/test_run.py` assert the table header row, the fenced blocks and that the
  output is identical across two renderings of the same document.

## 4. Call every tool that needs no arguments automatically

**Context.** A baseline needs a `calls.json`. Many servers have tools with no required
parameters (`list_projects`, `whoami`, `health`) that could be called without one.

**Acceptance criteria.**

- `--auto-calls` on `run` appends, after the calls from `--calls`, one call with empty
  arguments for every tool from `tools/list` whose `inputSchema` has no `required` entries
  (or an empty one) and that is not already in `--calls`. The order follows `tools/list`.
- Tools with `destructiveHint: true` are skipped and listed in a note on stdout, since a
  call is a real action.
- Tests in `tests/test_run.py` with the proxied fixture: `env` is called automatically,
  `fetch` (required `url`) is not, and a destructive tool added to the fixture for the test
  is skipped and named in the output.
- README options table gains the flag with the destructive-tool rule spelled out.

## 5. A composite GitHub Action for the baseline check

**Context.** The README shows a workflow that installs the tool and runs it. A composite
action in `action/` would make the check a two-line step and could upload `egress.json` as
an artifact.

**Acceptance criteria.**

- `action/action.yml` with inputs `command` (required, the server command), `calls`,
  `baseline` (default `egress.baseline.json`), `check` (default `true`), `out` (default
  `egress.json`), `python-version` (default `3.12`) and `version` (PyPI version to install,
  default: install from the checked-out repository). Outputs: `out` (the file path) and
  `new-hosts` (comma-separated).
- The action installs the tool with `pipx`, runs `mcp-egress run` with the inputs, and
  sets the outputs by reading `check.new_hosts` from the document with a short Python
  step. It never sets `NO_PROXY` or any proxy variable itself; the tool does that.
- A job in `.github/workflows/ci.yml` runs the action against
  `tests/fixtures/proxied_server.py` with `check: false` and prints the outputs, keeping
  `permissions: contents: read`.
- README "CI usage" shows the action form next to the existing plain workflow.
