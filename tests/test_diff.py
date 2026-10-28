import json
from pathlib import Path

import pytest

from mcp_egress.baseline import diff_documents, render_diff
from mcp_egress.cli import main


def document(hosts, tools=None):
    return {"hosts": [{"host": host, "port": port} for host, port in hosts], "tools": tools or []}


def files(tmp_path, old, new):
    paths = [tmp_path / "old.json", tmp_path / "new.json"]
    for path, value in zip(paths, [old, new], strict=True):
        path.write_text(json.dumps(value), encoding="utf-8")
    return [str(path) for path in paths]


def test_diff_added_removed_and_changed_tool_attribution(tmp_path, capsys):
    old = document(
        [("old.test", 443), ("same.test", 443)],
        [
            {"name": "fetch", "hosts": ["old.test:443", "same.test:443"]},
        ],
    )
    new = document(
        [("new.test", 443), ("same.test", 443)],
        [
            {"name": "fetch", "hosts": ["new.test:443", "same.test:443"]},
        ],
    )
    args = files(tmp_path, old, new)
    before = [Path(path).read_bytes() for path in args]
    assert main(["diff", *args]) == 1
    text = capsys.readouterr().out
    assert "added hosts (1)" in text and "new.test:443  (tools: fetch)" in text
    assert "removed hosts (1)" in text and "old.test:443  (tools: fetch)" in text
    assert "changed tools (1)" in text and "fetch" in text
    assert [Path(path).read_bytes() for path in args] == before


@pytest.mark.parametrize(
    "old,new,expected",
    [
        (document([("a.test", 443)]), document([]), 0),
        (document([("a.test", 443)]), document([("A.test", 443), ("a.test", 443)]), 0),
        (document([]), document([("a.test", 443)]), 1),
    ],
)
def test_diff_exit_codes_without_rerunning_server(tmp_path, old, new, expected, monkeypatch):
    def cannot_run(*_args, **_kwargs):
        pytest.fail("saved-document diff must never execute a server")

    monkeypatch.setattr("mcp_egress.cli.run_server", cannot_run)
    assert main(["diff", *files(tmp_path, old, new)]) == expected


def test_tool_only_host_changes_are_visible_but_do_not_change_global_gate():
    hosts = [("a.test", 443), ("b.test", 443)]
    old = document(hosts, [{"name": "fetch", "hosts": ["a.test:443"]}])
    new = document(hosts, [{"name": "fetch", "hosts": ["b.test:443"]}])
    result = diff_documents(old, new, "old.json")
    assert result.comparison.ok
    assert result.changed_tools["fetch"].new_hosts == ["b.test:443"]
    assert result.changed_tools["fetch"].missing_hosts == ["a.test:443"]
    assert "changed tools (1)" in render_diff(result)


def test_duplicate_tool_names_are_combined_and_order_is_not_a_change():
    old = document([], [{"name": "fetch", "hosts": ["A.test:443", "b.test:443"]}])
    new = document(
        [],
        [
            {"name": "fetch", "hosts": ["b.test:443"]},
            {"name": "fetch", "hosts": ["a.test:443"]},
        ],
    )
    assert not diff_documents(old, new, "old.json").changed_tools


@pytest.mark.parametrize(
    "value", [[], {}, {"hosts": None}, {"hosts": [None]}, {"hosts": [], "tools": [None]}]
)
def test_invalid_documents_exit_two(tmp_path, value, capsys):
    paths = files(tmp_path, document([]), value)
    assert main(["diff", *paths]) == 2
    assert "error:" in capsys.readouterr().err


def test_missing_and_malformed_json_exit_two(tmp_path):
    valid, missing = files(tmp_path, document([]), document([]))
    Path(missing).unlink()
    assert main(["diff", valid, missing]) == 2
    Path(missing).write_text("{", encoding="utf-8")
    assert main(["diff", valid, missing]) == 2


def test_diff_format_json_matches_text_content(tmp_path, capsys):
    old = document(
        [("old.test", 443)],
        [{"name": "fetch", "hosts": ["old.test:443"]}],
    )
    new = document(
        [("new.test", 443)],
        [{"name": "fetch", "hosts": ["new.test:443"]}],
    )
    paths = files(tmp_path, old, new)
    assert main(["diff", "--format", "json", *paths]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["added_hosts"] == {"new.test:443": ["fetch"]}
    assert payload["removed_hosts"] == {"old.test:443": ["fetch"]}
    assert payload["changed_tools"] == {
        "fetch": {"added": ["new.test:443"], "removed": ["old.test:443"]}
    }
    # default remains text
    assert main(["diff", *paths]) == 1
    text = capsys.readouterr().out
    assert "added hosts (1)" in text
    assert "new.test:443" in text
