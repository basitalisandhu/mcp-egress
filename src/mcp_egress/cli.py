"""Command line entry point: `mcp-egress run [options] -- <command...>`."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from . import __version__
from .analysis import warnings_for
from .baseline import BaselineError, compare, load_baseline
from .report import build_document, render_check, render_report, write_document
from .runner import RunError, load_calls, run_server

EXIT_OK = 0
EXIT_NEW_HOSTS = 1
EXIT_USAGE = 2
EXIT_SERVER = 3

DEFAULT_OUT = "egress.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-egress",
        description=(
            "Run an MCP server behind a recording proxy and list every host it contacts, "
            "per tool. Options go before `--`; everything after `--` is the server command."
        ),
    )
    parser.add_argument("--version", action="version", version=f"mcp-egress {__version__}")
    sub = parser.add_subparsers(dest="subcommand", metavar="COMMAND")
    run = sub.add_parser(
        "run",
        help="spawn a stdio server, run initialize, tools/list and optional calls",
        description=(
            "Spawn a stdio MCP server with HTTP_PROXY, HTTPS_PROXY and ALL_PROXY pointed "
            "at an embedded proxy and NO_PROXY cleared, run initialize and tools/list, "
            "then the calls from --calls, and write egress.json."
        ),
        usage="%(prog)s [options] -- <command> [args...]",
    )
    run.add_argument("--calls", metavar="FILE", help="JSON file of {tool, arguments} calls")
    run.add_argument(
        "--baseline",
        metavar="FILE",
        help="baseline egress.json: written when --check is absent, compared with --check",
    )
    run.add_argument("--check", action="store_true", help="exit 1 when a host is not in --baseline")
    run.add_argument(
        "--out",
        metavar="FILE",
        help=f"where to write the run document (default {DEFAULT_OUT})",
    )
    run.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        metavar="SECONDS",
        help="per-request timeout for initialize, tools/list and each call (default 30)",
    )
    run.add_argument(
        "--server-stderr",
        metavar="FILE",
        help="write the server's stderr to FILE instead of passing it through",
    )
    run.add_argument("command", nargs=argparse.REMAINDER, help="the server command")
    return parser


def split_command(argv: list[str]) -> tuple[list[str], list[str]]:
    """Split argv at the first `--`: options on the left, server command on the right."""
    if "--" in argv:
        index = argv.index("--")
        return argv[:index], argv[index + 1 :]
    return argv, []


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    options, command = split_command(args)
    parser = build_parser()
    ns = parser.parse_args(options)
    if ns.subcommand != "run":
        parser.print_help()
        return EXIT_USAGE
    command = [*ns.command, *command]
    if not command:
        parser.error("no server command given; put it after `--`")
    if ns.check and not ns.baseline:
        parser.error("--check needs --baseline FILE")
    return run_command(ns, command)


def run_command(ns: argparse.Namespace, command: list[str]) -> int:
    out = sys.stdout
    try:
        calls = load_calls(ns.calls) if ns.calls else []
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    baseline_doc = None
    if ns.check:
        try:
            baseline_doc = load_baseline(Path(ns.baseline))
        except BaselineError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE

    errlog = None
    if ns.server_stderr:
        errlog = open(ns.server_stderr, "w", encoding="utf-8")  # noqa: SIM115 - closed below
    try:
        result = asyncio.run(run_server(command, calls, timeout=ns.timeout, errlog=errlog))
    except RunError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_SERVER
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_SERVER
    finally:
        if errlog is not None:
            errlog.close()

    doc = build_document(result, warnings_for(result))
    print(render_report(doc), file=out)

    status = EXIT_OK
    if baseline_doc is not None:
        comparison = compare(doc, baseline_doc, ns.baseline)
        doc["check"] = comparison.to_dict()
        print("", file=out)
        print(render_check(doc, comparison), file=out)
        if not comparison.ok:
            status = EXIT_NEW_HOSTS

    out_path = Path(ns.out) if ns.out else Path(DEFAULT_OUT)
    skip_out = ns.out is None and ns.check and out_path.resolve() == Path(ns.baseline).resolve()
    if skip_out:
        print(f"Not overwriting baseline {ns.baseline}; pass --out to write the run.", file=out)
    else:
        write_document(doc, out_path)
        print(f"Wrote {out_path}", file=out)
    if ns.baseline and not ns.check:
        baseline_path = Path(ns.baseline)
        if baseline_path.resolve() != out_path.resolve() or skip_out:
            write_document(doc, baseline_path)
        print(f"Baseline saved to {baseline_path}", file=out)
    return status


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
