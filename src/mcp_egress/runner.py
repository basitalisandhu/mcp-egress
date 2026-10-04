"""Spawn the server behind the recording proxy and drive it with the mcp client."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import IO, Any

from mcp import types
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.exceptions import MCPError

from .analysis import network_evidence
from .proxy import RecordingProxy
from .recorder import PHASE_CALL, PHASE_LIST, PHASE_SHUTDOWN, Recorder, utc_now

PROXY_VARIABLES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
NO_PROXY_VARIABLES = ("NO_PROXY", "no_proxy")
SETTLE_SECONDS = 0.05


class RunError(Exception):
    """The server could not be started or driven through initialize and tools/list."""


@dataclass
class CallSpec:
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolInfo:
    name: str
    title: str | None
    description: str | None
    annotations: dict[str, Any] | None
    hosts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "annotations": self.annotations,
            "hosts": list(self.hosts),
        }


@dataclass
class CallOutcome:
    tool: str
    arguments: dict[str, Any]
    ok: bool
    is_error: bool
    error: str | None
    text: str
    hosts: list[str]
    network_evidence: str | None
    duration_ms: int

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "arguments": self.arguments,
            "ok": self.ok,
            "is_error": self.is_error,
            "error": self.error,
            "hosts": list(self.hosts),
            "network_evidence": self.network_evidence,
            "duration_ms": self.duration_ms,
        }


@dataclass
class ServerInfo:
    name: str
    version: str
    protocol_version: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "protocol_version": self.protocol_version,
        }


@dataclass
class RunResult:
    command: list[str]
    started: str
    finished: str
    proxy_url: str
    server: ServerInfo | None
    tools: list[ToolInfo]
    calls: list[CallOutcome]
    recorder: Recorder


def child_environment(proxy_url: str, base: dict[str, str] | None = None) -> dict[str, str]:
    """The environment the server runs with: everything inherited, proxies overridden.

    HTTP_PROXY, HTTPS_PROXY and ALL_PROXY (upper and lower case) point at the
    recording proxy, NO_PROXY and no_proxy are empty so loopback and private
    hosts are proxied too, and NODE_USE_ENV_PROXY=1 makes the built-in fetch of
    Node 24 and newer read those variables.
    """
    env = dict(os.environ if base is None else base)
    for name in PROXY_VARIABLES:
        env[name] = proxy_url
    for name in NO_PROXY_VARIABLES:
        env[name] = ""
    env["NODE_USE_ENV_PROXY"] = "1"
    return env


def load_calls(path: str) -> list[CallSpec]:
    """Read a calls file: a list of `{tool, arguments}` or `{"calls": [...]}`."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        data = data.get("calls")
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a list of calls or an object with a 'calls' list")
    calls: list[CallSpec] = []
    for index, entry in enumerate(data):
        if not isinstance(entry, dict) or not isinstance(entry.get("tool"), str):
            raise ValueError(f"{path}: call {index} needs a string 'tool'")
        arguments = entry.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError(f"{path}: call {index}: 'arguments' must be an object")
        calls.append(CallSpec(tool=entry["tool"], arguments=arguments))
    return calls


def result_text(result: types.CallToolResult) -> str:
    """The text of a tool result: its text content, or its structured content as JSON."""
    parts: list[str] = []
    for item in result.content:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            parts.append(text)
    if not parts and result.structured_content is not None:
        parts.append(json.dumps(result.structured_content, ensure_ascii=False))
    return "\n".join(parts)


def _leaf(exc: BaseException) -> BaseException:
    """The first non-group exception inside nested exception groups."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def _tool_info(tool: types.Tool) -> ToolInfo:
    annotations = None
    if tool.annotations is not None:
        annotations = tool.annotations.model_dump(by_alias=True, exclude_none=True)
    return ToolInfo(
        name=tool.name, title=tool.title, description=tool.description, annotations=annotations
    )


async def _list_all_tools(session: ClientSession) -> list[types.Tool]:
    tools: list[types.Tool] = []
    cursor: str | None = None
    while True:
        params = types.PaginatedRequestParams(cursor=cursor) if cursor else None
        page = await session.list_tools(params=params)
        tools.extend(page.tools)
        cursor = page.next_cursor
        if not cursor:
            return tools


async def _settle() -> None:
    """Give connections started just before a response a chance to be recorded."""
    await asyncio.sleep(SETTLE_SECONDS)


async def _call(
    session: ClientSession, spec: CallSpec, recorder: Recorder, proxy_url: str, timeout: float
) -> CallOutcome:
    start_index = len(recorder.connections)
    started = time.monotonic()
    ok, is_error, error, text = False, False, None, ""
    try:
        result = await session.call_tool(spec.tool, spec.arguments, read_timeout_seconds=timeout)
    except MCPError as exc:
        error = exc.message
    except Exception as exc:  # keep going after a broken tool
        error = f"{type(exc).__name__}: {exc}"
    else:
        if isinstance(result, types.CallToolResult):
            is_error = result.is_error
            text = result_text(result)
            ok = not is_error
            if is_error:
                error = text or "tool returned isError"
        else:
            error = f"unexpected result type {type(result).__name__}"
    await _settle()
    return CallOutcome(
        tool=spec.tool,
        arguments=spec.arguments,
        ok=ok,
        is_error=is_error,
        error=error,
        text=text,
        hosts=recorder.keys_since(start_index),
        network_evidence=network_evidence(text, (proxy_url,)) if ok else None,
        duration_ms=int((time.monotonic() - started) * 1000),
    )


async def run_server(
    command: list[str],
    calls: list[CallSpec],
    timeout: float = 30.0,
    errlog: IO[str] | None = None,
    startup_timeout: float | None = None,
) -> RunResult:
    """Run initialize, tools/list and the given calls with every proxy variable set.

    `timeout` bounds each tool call; `startup_timeout` bounds initialize and
    tools/list and defaults to `timeout`. Raises `RunError` when the server
    cannot be spawned or does not get through initialize and tools/list. Failed
    tool calls are recorded, not raised.
    """
    if startup_timeout is None:
        startup_timeout = timeout
    if not command:
        raise RunError("no server command given")
    recorder = Recorder()
    started = utc_now()
    server: ServerInfo | None = None
    tools: list[ToolInfo] = []
    outcomes: list[CallOutcome] = []
    async with RecordingProxy(recorder) as proxy:
        params = StdioServerParameters(
            command=command[0], args=list(command[1:]), env=child_environment(proxy.url)
        )
        try:
            async with (
                stdio_client(params, errlog=errlog or sys.stderr) as (read, write),
                ClientSession(read, write, read_timeout_seconds=startup_timeout) as session,
            ):
                recorder.set_phase(PHASE_LIST)
                init = await session.initialize()
                server = ServerInfo(
                    name=init.server_info.name,
                    version=init.server_info.version,
                    protocol_version=init.protocol_version,
                )
                tools = [_tool_info(t) for t in await _list_all_tools(session)]
                await _settle()
                for spec in calls:
                    recorder.set_phase(PHASE_CALL, spec.tool)
                    outcomes.append(await _call(session, spec, recorder, proxy.url, timeout))
                recorder.set_phase(PHASE_SHUTDOWN)
        except (OSError, ValueError) as exc:
            raise RunError(f"cannot start {command[0]!r}: {exc}") from exc
        except (MCPError, RuntimeError, BaseExceptionGroup) as exc:
            leaf = _leaf(exc)
            if isinstance(leaf, KeyboardInterrupt | SystemExit):
                raise leaf from None
            message = leaf.message if isinstance(leaf, MCPError) else str(leaf)
            raise RunError(f"server failed during {recorder.phase}: {message}") from exc
        await _settle()

    by_name = {tool.name: tool for tool in tools}
    for outcome in outcomes:
        tool = by_name.get(outcome.tool)
        if tool is None:
            continue
        for key in outcome.hosts:
            if key not in tool.hosts:
                tool.hosts.append(key)
    return RunResult(
        command=list(command),
        started=started,
        finished=utc_now(),
        proxy_url=proxy.url,
        server=server,
        tools=tools,
        calls=outcomes,
        recorder=recorder,
    )
