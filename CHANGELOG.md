# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/basitalisandhu/mcp-egress/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/basitalisandhu/mcp-egress/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/basitalisandhu/mcp-egress/releases/tag/v0.1.0
