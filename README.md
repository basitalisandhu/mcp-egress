# mcp-egress: record every host an MCP server contacts, per tool

Run a stdio MCP server behind a small recording proxy and get the exact set of hosts it contacts while you run `initialize`, `tools/list` and sample tool calls. Every host is attributed to the phase and the tool that reached it, written to `egress.json`, printed as a table, and printed again as two ready-to-paste blocks: Claude Code `WebFetch(domain:host)` permission rules and a sandbox allowed-domain list. Keep the file as a baseline and `--check` fails CI the day a tool starts talking to a host nobody declared.

[![CI](https://github.com/basitalisandhu/mcp-egress/actions/workflows/ci.yml/badge.svg)](https://github.com/basitalisandhu/mcp-egress/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

## Why

Tool calls reach hosts nobody declared. An MCP server's README says it talks to one API; the server is free to talk to anything, and a tool whose definition changed after you installed it can start sending data somewhere new without any visible change in behaviour. People are fighting this by hand: there is an open request to [auto-allowlist MCP server domains for code execution network egress](https://github.com/anthropics/claude-code/issues/70644) in Claude Code, and [eight open reports](https://github.com/anthropics/claude-code/issues/93562) that the sandbox egress allowlist is ignored or collapses to a built-in list. One security checklist for MCP puts it plainly: keep a per-server allowlist of outbound hosts, because [a new outbound host is the most reliable signal of a rug pull](https://corgea.com/learn/mcp-security-best-practices). An enterprise scorer reported in July 2026 that [184 popular MCP servers changed their tool definitions after publication](https://daily.dev/posts/ask-hn-what-are-you-working-on-july-2026--4oout57sw).

Static scanners read the code and cannot see what a server actually connects to. Runtime agent firewalls wrap the whole agent, not one server, and give you a policy to maintain rather than a list to start from. mcp-egress is the per-server audit in between: run the server once under a proxy, read the list, commit it, and let CI tell you when it grows.

Why the two paste blocks: in Claude Code, [only `WebFetch(domain:host)` permission rules add a host to the sandbox allowed-domain list](https://code.claude.com/docs/en/permissions); a bare rule does not. mcp-egress prints exactly those rules, and the same hosts as a plain JSON array for a sandbox configuration.

## How it works

1. An asyncio proxy starts on `127.0.0.1` on an ephemeral port. It accepts `CONNECT host:port` (the HTTPS path; bytes are tunnelled, never read) and plain absolute-form `GET http://host/...` requests.
2. The server command is spawned with `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` (and their lower-case forms) pointed at the proxy, `NO_PROXY` and `no_proxy` set to an empty string so loopback and private hosts are proxied too, and `NODE_USE_ENV_PROXY=1` so the built-in fetch of Node 24 and newer reads those variables. The rest of your environment is inherited unchanged.
3. The official `mcp` client runs `initialize` and `tools/list` (phase `list`), then every `{tool, arguments}` entry of `--calls` (phase `call`, tool name recorded).
4. Each connection is recorded as host, port, scheme, phase, tool, first-seen time and bytes in each direction. The server is stopped and `egress.json` is written.

Hosts are recorded as the server named them (DNS is resolved by the proxy), so the list is a list of names, not IP addresses.

## Install

Requires Python 3.11 or newer on Linux or macOS. PyPI publication is pending, so install from the repository:

```bash
pipx install git+https://github.com/basitalisandhu/mcp-egress                       # isolated CLI install
uvx --from git+https://github.com/basitalisandhu/mcp-egress mcp-egress --help       # run without installing
pip install git+https://github.com/basitalisandhu/mcp-egress                        # into the current environment
git clone https://github.com/basitalisandhu/mcp-egress && cd mcp-egress && uv venv && uv pip install -e ".[dev]"   # development
```

Once the package is on PyPI the short forms work too: `pipx install mcp-egress`, `uvx mcp-egress --help`, `pip install mcp-egress`. The only runtime dependency is `mcp` (2.0 or newer).

### Container image

Each release tag publishes `ghcr.io/basitalisandhu/mcp-egress` for linux/amd64 and linux/arm64, tagged with the version and `latest`. The image runs as uid 1000 with `/work` as the working directory:

```bash
docker run --rm -v "$PWD:/work" ghcr.io/basitalisandhu/mcp-egress:0.1.0 \
  run --calls calls.json --baseline egress.baseline.json --check --out egress.json -- python server.py
```

`mcp-egress run` starts the MCP server inside the container, so the server command has to work there. The image contains Python 3.12 and the `mcp` package and nothing else: a Python server in the mounted directory that needs only `mcp` and the standard library runs as is. Servers started with `npx`, `uvx` or another runtime need an image of your own that adds that runtime (`FROM ghcr.io/basitalisandhu/mcp-egress:0.1.0`), or a local install of mcp-egress. The baseline, `--check` and the `egress.json` document behave the same in the container; the mounted directory must be writable by uid 1000.

The image is signed with a keyless cosign signature and has a build provenance attestation and an SPDX SBOM (attached to the GitHub Release). To verify:

```bash
cosign verify ghcr.io/basitalisandhu/mcp-egress:0.1.0 \
  --certificate-identity-regexp '^https://github.com/basitalisandhu/mcp-egress/\.github/workflows/publish-github-packages\.yml@refs/tags/v' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
gh attestation verify oci://ghcr.io/basitalisandhu/mcp-egress:0.1.0 --repo basitalisandhu/mcp-egress
```

### pip

Once published to PyPI:

```bash
pip install mcp-egress
```

## Usage

```bash
mcp-egress run [options] -- <command> [args...]
```

Options go before `--`; everything after `--` is the server command, exactly as you would put it in an MCP client configuration.

| Option | What it does |
|---|---|
| `--calls FILE` | JSON file of calls to make after `tools/list`: a list of `{"tool": name, "arguments": {...}}`, or an object with a `calls` list. Without it only `initialize` and `tools/list` run. |
| `--out FILE` | Where to write the run document. Default `egress.json`. |
| `--baseline FILE` | Without `--check`: also save this run as the baseline. With `--check`: the baseline to compare against (never modified). |
| `--check` | Exit 1 when a `host:port` seen in this run is not in the baseline. Hosts in the baseline that were not seen are reported, not failed. |
| `--timeout SECONDS` | Per-request timeout for `initialize`, `tools/list` and each call. Default 30. A call that times out is recorded as failed; the run continues. |
| `--server-stderr FILE` | Write the server's stderr to a file instead of passing it through. |

Exit codes: `0` ok, `1` new hosts with `--check`, `2` usage error (bad options, unreadable calls file, missing baseline), `3` the server could not be started or did not get through `initialize` and `tools/list`.

A first run saves the baseline:

```bash
mcp-egress run --calls calls.json --baseline egress.baseline.json -- uvx some-mcp-server --api-key "$KEY"
```

Every later run in CI checks against it:

```bash
mcp-egress run --calls calls.json --baseline egress.baseline.json --check -- uvx some-mcp-server --api-key "$KEY"
```

`calls.json` holds the tool calls that exercise the server's network paths. Tools that are never called cannot reach anything, so call each tool at least once with representative arguments:

```json
[
  {"tool": "fetch", "arguments": {"url": "http://127.0.0.1:39211/items"}},
  {"tool": "tunnel", "arguments": {"url": "http://127.0.0.1:39211/health"}},
  {"tool": "ping", "arguments": {"url": "http://127.0.0.1:39211/"}},
  {"tool": "echo", "arguments": {"text": "no network"}}
]
```

## Sample output

The run below is real output against the test fixture in [`tests/fixtures/proxied_server.py`](tests/fixtures/proxied_server.py), a small server whose tools fetch URLs with `urllib` (which honours proxy variables), with a local HTTP server standing in for an API. The `ping` tool declares `openWorldHint: false` and fetches anyway, which is the contradiction the audit flags.

```text
$ mcp-egress run --calls calls.json --baseline baseline.json -- python fixtures/proxied_server.py
mcp-egress: python fixtures/proxied_server.py
server: proxied-fixture 0.1.0 (protocol 2025-11-25), 6 tool(s), 4 call(s), 2 host(s)

HOST       PORT   SCHEME  FIRST SEEN   TOOLS        CONNS  OUT    IN
127.0.0.1  39211  http    call:fetch   fetch, ping  2      243 B  278 B
127.0.0.1  39211  https   call:tunnel  tunnel       1      66 B   139 B

Claude Code permission rules (settings.json, permissions.allow):
"WebFetch(domain:127.0.0.1)",

Sandbox allowed domains (settings.json, sandbox.network.allowedDomains):
[
  "127.0.0.1"
]

Warnings:
  open-world-hint-false      ping: declares openWorldHint false but reached 127.0.0.1:39211
Wrote egress.json
Baseline saved to baseline.json
```

`SCHEME` is `https` for connections that arrived as `CONNECT` (the proxy tunnels them without reading) and `http` for absolute-form requests forwarded in the clear. `FIRST SEEN` is the phase and tool of the first connection; `TOOLS` lists every tool that reached the host.

The same run checked against a baseline that only knows `api.example.com:443`:

```text
$ mcp-egress run --calls calls.json --baseline old-baseline.json --check --out egress.json -- python fixtures/proxied_server.py
...
Baseline old-baseline.json: 1 new host(s):
  127.0.0.1:39211  (tools: fetch, ping, tunnel)
Wrote egress.json
```

Exit code 1. The second fixture, [`tests/fixtures/socket_server.py`](tests/fixtures/socket_server.py), fetches with a raw `http.client` connection that ignores proxy variables:

```text
$ mcp-egress run --calls calls.json --out socket.json -- python fixtures/socket_server.py
mcp-egress: python fixtures/socket_server.py
server: socket-fixture 0.1.0 (protocol 2025-11-25), 2 tool(s), 4 call(s), 0 host(s)

No proxied connections were seen.

Claude Code permission rules (settings.json, permissions.allow):
# no hosts seen, nothing to allow

Sandbox allowed domains (settings.json, sandbox.network.allowedDomains):
[]

Warnings:
  possible-proxy-bypass      fetch: result contains '200 OK' but no proxied connection was seen during the call; the server may ignore proxy variables
Wrote socket.json
```

### The two paste blocks

The first block goes into the `permissions.allow` array of a Claude Code settings file (`.claude/settings.json` in the project or `~/.claude/settings.json`):

```json
{
  "permissions": {
    "allow": [
      "WebFetch(domain:127.0.0.1)"
    ]
  }
}
```

The second block is the same hosts as a JSON array, for a sandbox allowed-domain list such as `sandbox.network.allowedDomains` in Claude Code settings or the allowlist of whatever sandbox runs your agent. Hosts are printed without ports and without wildcards; add `*.` prefixes yourself if a service uses many subdomains.

### Warnings

| Code | Meaning |
|---|---|
| `open-world-hint-false` | A tool annotated `openWorldHint: false` reached a host. Annotations are the server's own claims; this one was false. |
| `outside-declared-base-url` | The server command line contains a URL (for example `--base-url https://api.example.com`), and a tool reached a host other than the ones declared there. Only printed when the command line declares at least one URL. |
| `possible-proxy-bypass` | A tool call succeeded and its result contains an `http://` or `https://` URL, a status line such as `200 OK` or `HTTP/1.1 404 Not Found`, or a status field such as `status: 503`, while no proxied connection was seen during that call. The server probably reached the network without honouring the proxy variables. See the limits below. |

## The egress.json document

The document is the baseline format and the input for your own scripts. Its JSON Schema is [`schema/egress.schema.json`](schema/egress.schema.json) and the test suite validates every run against it.

| Key | Content |
|---|---|
| `format_version`, `generator` | `1`, and the tool name and version that wrote the file. |
| `command`, `started`, `finished`, `proxy` | The server command, UTC timestamps, and the proxy URL the server was given. |
| `server` | `name`, `version` and negotiated `protocol_version` from `initialize`, or `null`. |
| `hosts` | One entry per host, port and scheme: `host`, `port`, `scheme`, `phase` and `tool` of the first connection, `first_seen`, `bytes_out`, `bytes_in`, `connections`, and the `phases` and `tools` that reached it. |
| `tools` | Every tool from `tools/list` with `name`, `title`, `description`, `annotations` (as the server sent them) and the `host:port` list it reached. |
| `calls` | One entry per `--calls` entry: `tool`, `arguments`, `ok`, `is_error`, `error`, `hosts`, `network_evidence` (the fragment that looked like network output, if any) and `duration_ms`. |
| `warnings` | `{code, tool, message}` entries, the same ones printed. |
| `check` | `null`, or `{baseline, ok, new_hosts, missing_hosts}` when `--check` ran. |

`--check` compares `host:port` keys only; byte counts, tools and phases may change freely. A baseline needs nothing more than a `hosts` list, so you can also write one by hand.

## CI usage

```yaml
name: mcp-egress
on: [pull_request]
permissions:
  contents: read
jobs:
  egress:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pipx install git+https://github.com/basitalisandhu/mcp-egress
      - run: mcp-egress run --calls calls.json --baseline egress.baseline.json --check --out egress.json -- uvx some-mcp-server
        env:
          SOME_API_KEY: ${{ secrets.SOME_API_KEY }}
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: egress
          path: egress.json
```

When a tool legitimately needs a new host, re-run without `--check` and commit the new baseline in the same pull request as the change that needed it, so the review sees the host and the reason together.

## The proxy-bypass warning and its limits

mcp-egress sees only connections that go through the proxy, and a server goes through the proxy only if its HTTP stack honours the proxy environment variables. Most do: Python's `urllib`, `requests` and `httpx`, Go's `net/http`, `curl`, and the built-in fetch of Node 24 and newer when `NODE_USE_ENV_PROXY=1` is set (mcp-egress sets it). Some do not: raw sockets, custom HTTP stacks, older Node runtimes, and any client created with proxy support switched off. A server like that reaches the network directly and mcp-egress records nothing for it.

The `possible-proxy-bypass` warning is the only signal you get in that case, and it is a heuristic: it fires when a call succeeded with network-shaped output and no connection was seen. It cannot fire for a tool that reaches the network and returns nothing that looks like it, and it can fire for a tool that merely echoes a URL you passed in. Treat an empty host list for a tool that clearly talks to an API as a finding in itself.

Other things this tool does not observe:

- DNS. The proxy resolves names itself, so a server that exfiltrates through DNS queries or talks to a resolver directly is not seen.
- Anything inside a `CONNECT` tunnel. Hosts and ports, yes; paths, headers and payloads, no, by design.
- Remote (HTTP or Streamable HTTP) MCP servers. Version 0.1 spawns stdio servers only.
- Connections made by other processes on the machine. The proxy is unauthenticated for the duration of the run; another local process that finds the port can use it and its hosts would be recorded against the current phase.
- Tools you did not call. A list of hosts is only as complete as `calls.json`.

A Linux network-namespace mode that captures every connection regardless of proxy support is the planned answer to the first point of the list; see the roadmap.

## Frequently asked questions

**How do I find out which hosts an MCP server connects to?**
Run it once under `mcp-egress run` with a `calls.json` that exercises each tool: `mcp-egress run --calls calls.json -- uvx the-server`. The table lists every host and port the server contacted, which tool reached it, and how many bytes went each way; `egress.json` holds the same data for scripts. The method is a recording proxy plus the standard proxy environment variables, so it works for any server whose HTTP client honours `HTTPS_PROXY`, in any language, with no code changes and no root privileges.

**How do I allowlist an MCP server's domains in Claude Code?**
Run the server through mcp-egress and paste the printed `WebFetch(domain:host)` rules into the `permissions.allow` array of your settings file. The Claude Code permissions documentation says those rules are what adds a host to the sandbox allowed-domain list. mcp-egress also prints the hosts as a JSON array for `sandbox.network.allowedDomains` or any other sandbox configuration. Re-run with `--baseline` so the next change to the list is a reviewed diff rather than a surprise.

**Can a server hide its traffic from mcp-egress?**
Yes, if it ignores proxy variables: raw sockets, a custom HTTP stack, or a Node runtime older than 24 all connect directly and leave no record. mcp-egress prints `possible-proxy-bypass` when a tool's result looks like network output and no connection was seen, and prints `No proxied connections were seen` when the whole run was silent, but both are hints, not proof. Treat an empty host list for a tool that obviously talks to an API as a finding. A network-namespace mode that captures every connection on Linux is on the roadmap.

**Does mcp-egress see the content of requests, or my credentials?**
No. HTTPS goes through the proxy as a `CONNECT` tunnel, and the proxy copies bytes without reading them; only the host, the port and the byte counts are recorded. Plain `http://` requests are forwarded with their headers but nothing from them is stored either. `egress.json` contains the server command line as you typed it, so if you pass secrets as arguments rather than through the environment, they will be in the file; prefer the environment, which is inherited by the server and never written anywhere.

## Roadmap

- Linux network-namespace mode that captures every connection, proxy support or not.
- Remote servers over Streamable HTTP, with the proxy variables applied to the client side as well.
- Resolved IP addresses next to each host, and a Markdown report for pull request comments.
- Automatic calls for tools with no required arguments, so a baseline needs less hand-written input.
- A composite GitHub Action wrapping the check.

## Contributing

Issues and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md) and the written-out starter issues in [docs/good-first-issues.md](docs/good-first-issues.md). Run `make check` (ruff and pytest) before opening a pull request. Security problems: see [SECURITY.md](SECURITY.md).

## Sibling projects

More tools by the same author: https://github.com/basitalisandhu

- [mcp-tools-lint](https://github.com/basitalisandhu/mcp-tools-lint): lint the `tools/list` surface of an MCP server for schema dialect, annotation and naming problems.

## Licence

MIT, see [LICENSE](LICENSE). Copyright 2026 Muhammad Basit Ali.
