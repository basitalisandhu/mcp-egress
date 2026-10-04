# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | yes |

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting on this repository (Security tab, "Report a vulnerability") rather than a public issue. Include the version, the server command you ran (with secrets removed), the `egress.json` if it helps, and what you expected to happen.

You will get an acknowledgement within 7 days and a fix or a mitigation plan within 30 days for confirmed issues. Credit is given in the release notes unless you prefer otherwise.

## What the tool does with your machine and data

- **It runs the command you give it.** `mcp-egress run -- <command>` spawns that command as a child process with your full environment plus the proxy variables. It is no safer than running the server yourself. Audit untrusted servers in a container or a throwaway machine.
- **The proxy listens on 127.0.0.1 only**, on an ephemeral port, for the duration of the run, and is closed before the tool exits. It never binds another interface.
- **The proxy is unauthenticated** while it runs. Any local process that discovers the port can use it as an open forwarding proxy to any host, and those connections would be recorded as if the server made them. The window is the length of one run, and the proxy only forwards; it grants no access the local process did not already have.
- **It records hosts, not payloads.** HTTPS goes through as a `CONNECT` tunnel and the proxy copies bytes without inspecting them; only the host, the port and the byte counts are kept. Plain `http://` requests are forwarded with their headers and nothing from them is stored. Tool results are scanned in memory for the proxy-bypass heuristic and are not written to disk.
- **`egress.json` contains the server command line verbatim**, tool names, descriptions and annotations from `tools/list`, the arguments from your `--calls` file, and hosts. If you pass secrets as command-line arguments or in call arguments, they end up in the file. Pass secrets through the environment instead; it is inherited by the server and never written.
- **It makes no network connections of its own** other than the ones the audited server asks the proxy to make. It does not phone home, check for updates or send telemetry.

## Limitations that matter for security conclusions

- A server whose HTTP stack ignores proxy variables (raw sockets, custom stacks, older Node runtimes) connects directly and is not observed. The `possible-proxy-bypass` warning is a heuristic over tool output, not a detector of direct connections. An empty host list is not proof of no egress.
- DNS queries are not observed; the proxy resolves names itself.
- Only stdio servers are supported in 0.1; remote servers are out of scope.
- Only tools that your `--calls` file exercises can be observed reaching anything.
- The baseline check compares `host:port` only. A server that keeps talking to the same host but sends different data is not detected; that is a job for the credential broker and audit log in the sibling projects.

## Scope of reports

Issues of interest: the proxy forwarding to hosts it should not (for example honouring a `CONNECT` to the proxy's own port in a loop), request parsing that could be used to confuse the recorded host, path handling in `--out`, `--baseline` and `--server-stderr`, and dependency vulnerabilities. Findings produced by the tool about an MCP server are not vulnerabilities in the tool; if a warning is wrong or missing, open a normal issue.
