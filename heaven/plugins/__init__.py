"""HEAVEN runtime plugin discovery.

This package lets external modules register capabilities that can be listed or
invoked from the CLI without changing the core scan engine.
"""

from __future__ import annotations

from heaven.plugins.manager import (
    PluginSpec,
    call_hook,
    demo_enabled,
    discover_plugins,
    enrich_findings,
    get_report_sections,
    load_plugin,
    run_plugin,
)

__all__ = [
    "PluginSpec",
    "call_hook",
    "demo_enabled",
    "discover_plugins",
    "enrich_findings",
    "get_report_sections",
    "load_plugin",
    "run_plugin",
]
