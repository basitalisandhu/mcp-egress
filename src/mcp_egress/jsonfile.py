"""Read a JSON input file (a baseline, a calls file) with errors that name the file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import _jsondepth


class JsonFileError(ValueError):
    """The file cannot be read as JSON; the message names the file and the reason."""


def read_json(path: str | Path) -> Any:
    """Parse a UTF-8 JSON file. A UTF-8 byte order mark is accepted.

    Raises FileNotFoundError when the file is missing and JsonFileError for every other
    problem: unreadable, UTF-16, not UTF-8, not JSON, or nested too deeply for the
    parser (which raised RecursionError, a traceback, before).
    """
    raw = Path(path).read_bytes() if Path(path).exists() else None
    if raw is None:
        raise FileNotFoundError(f"{path} does not exist")
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        raise JsonFileError(f"{path} is UTF-16 text; save it as UTF-8")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise JsonFileError(
            f"{path} is not UTF-8 text (byte {exc.start}); save it as UTF-8"
        ) from None
    try:
        return _jsondepth.loads(text)
    except RecursionError:
        raise JsonFileError(f"{path} is nested too deeply to read") from None
    except ValueError as exc:
        raise JsonFileError(f"{path} is not valid JSON: {exc}") from None
