"""Seeded fuzz and scaling tests for every input reader.

Baselines and calls files come from people and from CI caches; request heads come from
whatever the server under test sends to the proxy. Bad input must end in a clear error
naming the file (exit 2) or a 400 from the proxy, never a traceback, and each case runs
under a time limit so a hang fails instead of stalling CI.
"""

from __future__ import annotations

import contextlib
import json
import random
import threading
import time
from typing import Any

import pytest

from mcp_egress.baseline import (
    BaselineError,
    compare,
    diff_documents,
    load_baseline,
    render_diff,
)
from mcp_egress.cli import main
from mcp_egress.proxy import (
    ProxyError,
    parse_absolute_target,
    parse_connect_target,
    parse_head,
)
from mcp_egress.runner import load_calls

TIME_LIMIT = 60.0
SCALARS: list[Any] = [None, True, 0, -1, 2**70, "", "x", "[::1]:443", ":443", "h:abc", "h:99999"]
SCALARS += ["\udcff", [], {}, "a" * 3000, 1.5]
BASE = {
    "format_version": 1,
    "hosts": [
        {
            "host": "api.example.com",
            "port": 443,
            "scheme": "tunnel",
            "phase": "call",
            "tool": "t",
            "tools": ["t"],
            "connections": 1,
            "bytes_out": 1,
            "bytes_in": 2,
        }
    ],
    "tools": [{"name": "t", "hosts": ["api.example.com:443"]}, {"name": "u", "hosts": []}],
    "calls": [{"tool": "t", "arguments": {}}],
    "warnings": [],
    "server": None,
    "command": ["x"],
    "check": None,
}
KEYS = ["hosts", "tools", "host", "port", "name", "calls", "arguments", "tool"]


def _mutate(rng: random.Random, value: Any, depth: int = 0) -> Any:
    if rng.random() < 0.15 or depth > 6:
        return rng.choice(SCALARS)
    if isinstance(value, list):
        out = [_mutate(rng, x, depth + 1) for x in value]
        return out + ([rng.choice(SCALARS)] if rng.random() < 0.2 else [])
    if isinstance(value, dict):
        out = {
            k: (x if rng.random() < 0.6 else _mutate(rng, x, depth + 1)) for k, x in value.items()
        }
        out = {k: v for k, v in out.items() if rng.random() > 0.1}
        if rng.random() < 0.3:
            out[rng.choice(KEYS)] = rng.choice(SCALARS)
        return out
    return rng.choice(SCALARS) if rng.random() < 0.3 else value


def _within_limit(func, *args) -> Any:
    outcome: dict[str, Any] = {}

    def target() -> None:
        try:
            outcome["value"] = func(*args)
        except BaseException as exc:  # pragma: no cover - re-raised below
            outcome["error"] = exc

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(TIME_LIMIT)
    assert not worker.is_alive(), f"did not finish in {TIME_LIMIT}s"
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")


def _diff_round(tmp_path, seed: int) -> None:
    rng = random.Random(seed)
    for i in range(100):
        a, b = tmp_path / "a.json", tmp_path / "b.json"
        a.write_text(json.dumps(_mutate(rng, BASE)))
        b.write_text(json.dumps(_mutate(rng, BASE)))
        with contextlib.suppress(BaselineError):
            render_diff(diff_documents(load_baseline(a), load_baseline(b), "a.json"))
        calls = tmp_path / "calls.json"
        calls.write_text(
            json.dumps(_mutate(rng, {"calls": [{"tool": "t", "arguments": {"x": i}}]}))
        )
        with contextlib.suppress(ValueError):
            load_calls(str(calls))


@pytest.mark.parametrize("seed", range(4))
def test_mutated_baselines_and_calls_never_crash(tmp_path, seed: int) -> None:
    _within_limit(_diff_round, tmp_path, seed)


def test_request_heads_never_raise_anything_but_proxy_error() -> None:
    rng = random.Random(9110)
    alphabet = "CONNECT GET http://[::1]:80/ HTTP/1.1\r\n:x \x00\xff"
    for _ in range(3000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randrange(60)))
        for parse, value in (
            (parse_head, text.encode("latin-1")),
            (parse_connect_target, text),
            (parse_absolute_target, text),
        ):
            with contextlib.suppress(ProxyError):
                parse(value)


def test_unclosed_ipv6_target_is_a_proxy_error() -> None:
    # It raised ValueError, which the proxy swallowed: the client got no 400.
    with pytest.raises(ProxyError, match="bad request target"):
        parse_absolute_target("http://[::1/x")


BAD_FILES = {
    "utf16.json": (b"\xff\xfe{\x00}\x00", "is UTF-16 text; save it as UTF-8"),
    "latin1.json": (b'{"hosts":[{"host":"caf\xe9","port":1}]}', "is not UTF-8 text"),
    "deep.json": (b'{"a":' * 100_000 + b"1" + b"}" * 100_000, "is nested too deeply to read"),
    "deep-array.json": (b"[" * 100_000 + b"]" * 100_000, "is nested too deeply to read"),
    "empty.json": (b"", "is not valid JSON"),
}


@pytest.mark.parametrize("name", sorted(BAD_FILES))
def test_bad_input_files_exit_2_naming_the_file(tmp_path, capsys, name: str) -> None:
    content, message = BAD_FILES[name]
    path = tmp_path / name
    path.write_bytes(content)
    for args in (
        ["diff", str(path), str(path)],
        ["run", "--calls", str(path), "--", "true"],
        ["run", "--baseline", str(path), "--check", "--", "true"],
    ):
        assert main(args) == 2, args
        err = capsys.readouterr().err
        assert name in err and message in err, err
        assert "Traceback" not in err


def test_byte_order_mark_is_accepted(tmp_path) -> None:
    path = tmp_path / "bom.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(BASE).encode())
    assert load_baseline(path)["hosts"][0]["host"] == "api.example.com"


def _document(n: int, shift: int = 0, tools: int = 50) -> dict:
    hosts = [
        {"host": f"h{i}.example.com", "port": 443, "tools": [f"t{i % tools}"]}
        for i in range(shift, n + shift)
    ]
    by_tool = [
        {
            "name": f"t{j}",
            "hosts": [f"h{i}.example.com:443" for i in range(shift, n + shift) if i % tools == j],
        }
        for j in range(tools)
    ]
    return {"hosts": hosts, "tools": by_tool}


def test_compare_and_diff_are_linear_in_hosts() -> None:
    # 20,000 hosts: compare took 2.94 s and diff 3.32 s while host keys were kept in
    # lists; with sets both take a few hundredths of a second.
    old, new = _document(20_000), _document(20_000, shift=2_000)
    start = time.perf_counter()
    comparison = compare(new, old, "old.json")
    result = diff_documents(old, new, "old.json")
    render_diff(result)
    elapsed = time.perf_counter() - start
    assert len(comparison.new_hosts) == 2_000
    assert len(result.removed_hosts) == 2_000
    assert elapsed < 1.5, f"took {elapsed:.2f}s"
