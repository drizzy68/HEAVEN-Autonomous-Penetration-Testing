"""HEAVEN runtime plugin discovery.

This package lets external modules register capabilities that can be listed or
invoked from the CLI without changing the core scan engine.
"""

from __future__ import annotations

from heaven.plugins.manager import (
    PluginLoadError,
    PluginSpec,
    call_hook,
    clear_plugin_cache,
    demo_enabled,
    discover_plugins,
    enrich_findings,
    get_report_sections,
    load_plugin,
    plugin_load_errors,
    run_plugin,
)

__all__ = [
    "PluginLoadError",
    "PluginSpec",
    "call_hook",
    "clear_plugin_cache",
    "demo_enabled",
    "discover_plugins",
    "enrich_findings",
    "get_report_sections",
    "load_plugin",
    "plugin_load_errors",
    "run_plugin",
]
