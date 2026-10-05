"""Baseline loading and comparison."""

from __future__ import annotations

import json

import pytest

from mcp_egress.baseline import (
    BaselineError,
    compare,
    document_host_keys,
    load_baseline,
    tools_reaching,
)


def _doc(*keys: str, tools=None):
    hosts = []
    for key in keys:
        host, port = key.rsplit(":", 1)
        hosts.append({"host": host, "port": int(port)})
    return {"hosts": hosts, "tools": tools or []}


def test_compare_lists_new_and_missing_hosts_in_order():
    current = _doc("api.example:443", "cdn.example:443", "new.example:80")
    baseline = _doc("api.example:443", "gone.example:443")
    result = compare(current, baseline, "b.json")
    assert result.new_hosts == ["cdn.example:443", "new.example:80"]
    assert result.missing_hosts == ["gone.example:443"]
    assert result.ok is False
    assert result.to_dict() == {
        "baseline": "b.json",
        "ok": False,
        "new_hosts": ["cdn.example:443", "new.example:80"],
        "missing_hosts": ["gone.example:443"],
    }


def test_compare_is_ok_when_nothing_is_new_even_if_baseline_has_more():
    result = compare(_doc("a.example:443"), _doc("a.example:443", "b.example:443"), "b.json")
    assert result.ok and result.new_hosts == [] and result.missing_hosts == ["b.example:443"]


def test_document_host_keys_dedupes_and_lowercases():
    doc = {"hosts": [{"host": "A.example", "port": 443}, {"host": "a.example", "port": 443}]}
    assert document_host_keys(doc) == ["a.example:443"]
    with pytest.raises(BaselineError):
        document_host_keys({"hosts": [{"host": "x"}]})


def test_address_changes_do_not_change_baseline_comparison():
    current = _doc("api.example:443")
    baseline = _doc("api.example:443")
    current["hosts"][0]["addresses"] = ["127.0.0.2"]
    baseline["hosts"][0]["addresses"] = ["127.0.0.1"]
    assert compare(current, baseline, "b.json").ok


def test_load_baseline_errors(tmp_path):
    with pytest.raises(BaselineError, match="does not exist"):
        load_baseline(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(BaselineError, match="cannot read"):
        load_baseline(bad)
    nohosts = tmp_path / "nohosts.json"
    nohosts.write_text(json.dumps({"tools": []}))
    with pytest.raises(BaselineError, match="no 'hosts' list"):
        load_baseline(nohosts)
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_doc("a.example:443")))
    assert document_host_keys(load_baseline(good)) == ["a.example:443"]


def test_tools_reaching_names_the_tools_for_a_host():
    doc = _doc(
        "a.example:443",
        tools=[
            {"name": "fetch", "hosts": ["a.example:443"]},
            {"name": "echo", "hosts": []},
            {"name": "search", "hosts": ["a.example:443", "b.example:443"]},
        ],
    )
    assert tools_reaching(doc, "a.example:443") == ["fetch", "search"]
    assert tools_reaching(doc, "zzz:1") == []
