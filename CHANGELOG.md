# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.1] - 2026-10-29

### Added

- `mcp-egress diff --format json OLD NEW` prints the added and removed hosts as a JSON object for CI scripts; text stays the default and exit codes are unchanged (#33, #34 by @HarshRajSinghania).

### Fixed

- A deeply nested baseline or calls file exits 2 with "is nested too deeply to read" on every supported Python. Python 3.14 no longer raises `RecursionError` from `json.loads` at the old depth (balanced input parsed, unclosed input was reported as invalid JSON), so JSON is now checked for nesting first (limit 200 levels).
- CI tests Python 3.14.

## [0.3.0] - 2026-10-28

### Added

- A composite GitHub Action in `action/` (`uses: basitalisandhu/mcp-egress/action@v0.3.0`): inputs `command`, `calls`, `baseline`, `check`, `out`, `python-version`, `version`; outputs `out` and `new-hosts`; a new host still fails the step after the outputs are set. CI runs it against the fixture server. Closes #12.
- README: Troubleshooting section with the real messages and their fixes.
- `scripts/e2e_quickstart.sh` (`make e2e`) installs the checkout into a new virtual environment and runs the README quick start against the fixture server and a local web server: record, check, a new host, then `diff`. CI runs it.
- Seeded fuzz tests over baselines, calls files and proxy request heads, with time limits.
- `mcp-egress diff OLD.json NEW.json` compares saved documents offline, showing added/removed hosts with tool attribution and changed per-tool host lists; it reuses baseline comparison and never modifies either file (#9).

### Fixed

- A baseline or calls file nested tens of thousands of levels deep crashed with `RecursionError`; it is now an error naming the file (exit 2).
- A calls file that was not UTF-8 printed only the decoder message, without the file name; baselines and calls files now say which file is UTF-16 or not UTF-8. A UTF-8 byte order mark is accepted.
- An absolute-form proxy request with an unclosed IPv6 bracket (`http://[::1/x`) raised inside the proxy and the connection was dropped without an answer; it now gets a 400.

### Changed

- Host comparisons (`--check`, `diff`) use sets instead of list scans: 20,000 hosts took 2.94 s to compare and 3.32 s to diff, now 0.01 s and 0.04 s. A scaling test guards it.

## [0.2.0] - 2026-10-20

### Added

- `hidden-characters` warning: a tool whose `name`, `title` or `description` contains invisible or bidi-control characters (Unicode format characters such as zero-width spaces, bidi overrides and isolates, the byte order mark and tag characters, plus the variation selectors supplement) is flagged, with each code point named and any tag-character text decoded. It runs on the `tools/list` result, so it needs no calls and no network. The schema's warning `code` enum gains the value. Suggested by @rezearcher in #19.
- `run --format markdown`: the report as GitHub-flavoured Markdown (hosts table, the two paste blocks as fenced code, warnings as a list and, with `--check`, the new hosts), for a pull request comment or `$GITHUB_STEP_SUMMARY`. Status lines move to stderr in this mode so stdout is pure Markdown. `--format text` stays the default. (#10)

### Fixed

- `--check` validates every `hosts` entry of the baseline before the server starts. A hand-written baseline with a missing host or a port that is not a number now exits 2 with the file name and the bad value, instead of running the server and then stopping with a traceback. A port written as a numeric string (`"443"`) is accepted.
- The proxy answers `400 Bad Request` to an absolute-form request whose port is out of range (`http://host:99999/`) instead of dropping the connection without a reply.

### Changed

- README: a first screen with who the tool is for, a three-line quick start and a real run.

## [0.1.1] - 2026-10-06

### Fixed

- `schema/egress.schema.json`: `addresses` on a host is optional again (the `required` list is as before the addresses change), so recordings written before it was added still validate under `format_version` 1. Files written by 0.1.1 and later carry `addresses`.

### Changed

- Removed the umbrella branding; this project stands alone and links its sibling repositories directly.

## [0.1.0] - 2026-10-04

### Added

- Container image `ghcr.io/basitalisandhu/mcp-egress` for linux/amd64 and linux/arm64, published on each version tag with an SPDX SBOM, a build provenance attestation and a keyless cosign signature. The image runs as uid 1000 with `/work` as the working directory and includes Python and `mcp`, so `run` works for Python servers that need nothing else.
- `mcp-egress run -- <command...>`: spawns a stdio MCP server with `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` (upper and lower case) pointed at an embedded asyncio proxy, `NO_PROXY` and `no_proxy` cleared and `NODE_USE_ENV_PROXY=1`, inheriting the rest of the environment.
- The proxy accepts `CONNECT host:port` and absolute-form plain HTTP requests, listens on 127.0.0.1 on an ephemeral port, and records host, port, scheme, phase, tool, first-seen time and bytes in each direction.
- `initialize` and `tools/list` run in phase `list`; `--calls FILE` runs `{tool, arguments}` entries in phase `call` with the tool name recorded.
- `egress.json` output (`--out`) with `command`, `started`, `finished`, `server`, `hosts`, `tools` (with annotations and the hosts each reached), `calls`, `warnings` and `check`; JSON Schema in `schema/egress.schema.json`.
- Terminal report: hosts table, Claude Code `WebFetch(domain:host)` rules and a sandbox allowed-domain list, ready to paste.
- Warnings: `open-world-hint-false`, `outside-declared-base-url` and `possible-proxy-bypass`.
- `--baseline FILE` saves a baseline; `--baseline FILE --check` exits 1 and lists hosts not in it.
- `--timeout` per request and `--server-stderr` to capture the server's log.
- Test suite with two fixture servers (one honours proxy variables, one uses direct sockets) and a local HTTP server; CI on Python 3.11 and 3.12 on Ubuntu and macOS; PyPI trusted publishing on tags (off until the repository variable `PYPI_PUBLISH` is set).

### Changed

- Renamed the umbrella project from Hisar to Masoon; links, names and identifiers updated.

[Unreleased]: https://github.com/basitalisandhu/mcp-egress/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/basitalisandhu/mcp-egress/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/basitalisandhu/mcp-egress/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/basitalisandhu/mcp-egress/releases/tag/v0.1.0
