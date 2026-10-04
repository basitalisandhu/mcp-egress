# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- Renamed the umbrella project from Hisar to Masoon; links, names and identifiers updated.

## [0.1.0] - 2026-10-03

### Added

- `mcp-egress run -- <command...>`: spawns a stdio MCP server with `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` (upper and lower case) pointed at an embedded asyncio proxy, `NO_PROXY` and `no_proxy` cleared and `NODE_USE_ENV_PROXY=1`, inheriting the rest of the environment.
- The proxy accepts `CONNECT host:port` and absolute-form plain HTTP requests, listens on 127.0.0.1 on an ephemeral port, and records host, port, scheme, phase, tool, first-seen time and bytes in each direction.
- `initialize` and `tools/list` run in phase `list`; `--calls FILE` runs `{tool, arguments}` entries in phase `call` with the tool name recorded.
- `egress.json` output (`--out`) with `command`, `started`, `finished`, `server`, `hosts`, `tools` (with annotations and the hosts each reached), `calls`, `warnings` and `check`; JSON Schema in `schema/egress.schema.json`.
- Terminal report: hosts table, Claude Code `WebFetch(domain:host)` rules and a sandbox allowed-domain list, ready to paste.
- Warnings: `open-world-hint-false`, `outside-declared-base-url` and `possible-proxy-bypass`.
- `--baseline FILE` saves a baseline; `--baseline FILE --check` exits 1 and lists hosts not in it.
- `--timeout` per request and `--server-stderr` to capture the server's log.
- Test suite with two fixture servers (one honours proxy variables, one uses direct sockets) and a local HTTP server; CI on Python 3.11 and 3.12 on Ubuntu and macOS; PyPI trusted publishing on tags.

[Unreleased]: https://github.com/basitalisandhu/mcp-egress/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/basitalisandhu/mcp-egress/releases/tag/v0.1.0
