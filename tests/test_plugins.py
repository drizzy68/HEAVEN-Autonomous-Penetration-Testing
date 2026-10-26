"""Tests for the runtime plugin layer.

The plugin layer is deliberately best-effort: one broken plugin must never stop
the healthy ones from loading, and a failing hook must never abort a scan. That
makes silence the dangerous failure mode, so most of these tests assert both
halves of the contract — the broken plugin is skipped *and* reported.
"""

from __future__ import annotations

import logging
import os
import textwrap

import pytest

from heaven.plugins import manager


@pytest.fixture(autouse=True)
def isolated_plugin_state(monkeypatch):
    """Keep discovery deterministic and free of developer-local plugins."""

    monkeypatch.delenv("HEAVEN_PLUGIN_PATH", raising=False)
    monkeypatch.delenv("HEAVEN_ENABLE_DEMO", raising=False)
    manager.clear_plugin_cache()
    yield
    manager.clear_plugin_cache()


def _write(directory, filename: str, source: str):
    path = directory / filename
    path.write_text(textwrap.dedent(source))
    return path


def _discover(directory):
    return manager.discover_plugins([str(directory)])


def _failures_under(directory):
    return [e for e in manager.plugin_load_errors() if str(directory) in e.path]


def _touch(path):
    """Force a signature change even on coarse-mtime filesystems."""

    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


def test_bundled_demo_is_dormant_by_default():
    assert "demo" not in [p.name for p in manager.discover_plugins()]


def test_bundled_demo_loads_when_enabled(monkeypatch):
    monkeypatch.setenv("HEAVEN_ENABLE_DEMO", "1")
    assert "demo" in [p.name for p in manager.discover_plugins()]


def test_broken_plugin_does_not_hide_a_healthy_one(tmp_path):
    _write(tmp_path, "good.py", 'PLUGIN = {"name": "good", "description": "ok"}')
    _write(tmp_path, "broken.py", "import module_that_does_not_exist\n")

    assert "good" in [p.name for p in _discover(tmp_path)]

    errors = _failures_under(tmp_path)
    assert [e.reason for e in errors] == ["import"]
    assert "module_that_does_not_exist" in errors[0].error


def test_file_without_an_entry_point_is_reported(tmp_path):
    _write(tmp_path, "helper.py", "VALUE = 1\n")

    _discover(tmp_path)

    errors = _failures_under(tmp_path)
    assert [e.reason for e in errors] == ["no-entry-point"]
    assert "PLUGIN dict" in errors[0].error


def test_load_errors_survive_a_cache_hit(tmp_path):
    _write(tmp_path, "broken.py", "import module_that_does_not_exist\n")

    _discover(tmp_path)
    first = [(e.path, e.reason) for e in _failures_under(tmp_path)]
    _discover(tmp_path)
    second = [(e.path, e.reason) for e in _failures_under(tmp_path)]

    assert first == second


def test_fixing_a_plugin_clears_its_error(tmp_path):
    broken = _write(tmp_path, "broken.py", "import module_that_does_not_exist\n")
    _discover(tmp_path)
    assert [e.reason for e in _failures_under(tmp_path)] == ["import"]

    broken.write_text('PLUGIN = {"name": "broken", "description": "fixed"}\n')
    _touch(broken)

    assert "broken" in [p.name for p in _discover(tmp_path)]
    assert _failures_under(tmp_path) == []


def test_discovery_executes_each_module_once(tmp_path, monkeypatch):
    log = tmp_path / "loads.txt"
    monkeypatch.setenv("COUNTER_LOG", str(log))
    _write(
        tmp_path,
        "counter.py",
        """
        import os
        import pathlib

        pathlib.Path(os.environ["COUNTER_LOG"]).open("a").write("load\\n")
        PLUGIN = {"name": "counter", "description": "counts loads"}
        """,
    )

    for _ in range(5):
        _discover(tmp_path)

    assert log.read_text().count("load") == 1


def test_editing_a_plugin_invalidates_the_cache(tmp_path, monkeypatch):
    log = tmp_path / "loads.txt"
    monkeypatch.setenv("COUNTER_LOG", str(log))
    plugin = _write(
        tmp_path,
        "counter.py",
        """
        import os
        import pathlib

        pathlib.Path(os.environ["COUNTER_LOG"]).open("a").write("load\\n")
        PLUGIN = {"name": "counter", "description": "counts loads"}
        """,
    )

    _discover(tmp_path)
    plugin.write_text(plugin.read_text() + "\n# edited\n")
    _touch(plugin)
    _discover(tmp_path)

    assert log.read_text().count("load") == 2


def test_failing_hook_is_logged_and_isolated(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("HEAVEN_PLUGIN_PATH", str(tmp_path))
    _write(
        tmp_path,
        "bad.py",
        """
        PLUGIN = {"name": "bad", "description": "raises"}

        def hook_before_scan(**kwargs):
            raise ValueError("boom")
        """,
    )
    _write(
        tmp_path,
        "good.py",
        """
        PLUGIN = {"name": "good", "description": "healthy"}

        def hook_before_scan(**kwargs):
            return {"ok": True}
        """,
    )

    with caplog.at_level(logging.WARNING, logger="heaven.plugins.manager"):
        results = manager.call_hook("before_scan", scan_id="s")

    statuses = {r["plugin"]: r["status"] for r in results}
    assert statuses == {"bad": "error", "good": "ok"}

    failure = next(r for r in results if r["plugin"] == "bad")
    assert failure["error"] == "ValueError: boom"

    messages = [r.getMessage() for r in caplog.records]
    assert any("'bad'" in m and "hook before_scan failed" in m and "boom" in m for m in messages)


def test_failing_enrichment_hook_is_logged_and_skipped(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("HEAVEN_PLUGIN_PATH", str(tmp_path))
    _write(
        tmp_path,
        "bad.py",
        """
        PLUGIN = {"name": "bad", "description": "raises"}

        def hook_enrich_findings(*, findings=None, **kwargs):
            raise RuntimeError("boom enrich")
        """,
    )

    with caplog.at_level(logging.WARNING, logger="heaven.plugins.manager"):
        findings = [{"title": "real"}]
        assert manager.enrich_findings(findings) == findings

    assert any("hook enrich_findings failed" in r.getMessage() for r in caplog.records)


def test_failing_report_hook_is_logged_and_skipped(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("HEAVEN_PLUGIN_PATH", str(tmp_path))
    _write(
        tmp_path,
        "bad.py",
        """
        PLUGIN = {"name": "bad", "description": "raises"}

        def hook_report(*, summary=None, **kwargs):
            raise KeyError("boom report")
        """,
    )

    with caplog.at_level(logging.WARNING, logger="heaven.plugins.manager"):
        assert manager.get_report_sections({}, target="example.com") == []

    assert any("hook report failed" in r.getMessage() for r in caplog.records)
