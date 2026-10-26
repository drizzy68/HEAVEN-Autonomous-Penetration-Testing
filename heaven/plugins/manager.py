"""Plugin discovery and execution for HEAVEN.

Plugins may be placed in any of the following locations:
- ./heaven_plugins/
- ~/.heaven/plugins/
- ~/.config/heaven/plugins/
- heaven/plugins/ (bundled examples)

A plugin module may export either a dict named PLUGIN or a function named run.
Files that fail to load are recorded in `plugin_load_errors()` and reported by
`heaven plugins list`, so a broken plugin is never silently absent.
"""

from __future__ import annotations

import importlib.util
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PluginSpec:
    """Metadata for a discovered HEAVEN plugin."""

    name: str
    description: str
    version: str = "0.1.0"
    author: str = "unknown"
    source: str = ""
    path: str = ""
    entry_point: str = "run"
    module: ModuleType | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.name} {self.version} — {self.description}"


@dataclass(slots=True)
class PluginLoadError:
    """A plugin file that discovery skipped, and why.

    Discovery is best-effort: one broken plugin must never stop the rest from
    loading, or take a scan down with it. Recording the failure keeps that
    isolation without hiding the problem, so `heaven plugins list` can explain
    why an expected plugin never ran.
    """

    path: str
    source: str
    reason: str  # "import" (the module raised) or "no-entry-point"
    error: str

    def __str__(self) -> str:
        return f"{Path(self.path).name}: {self.error}"


def _candidate_directories(paths: Iterable[str] | None = None) -> list[Path]:
    candidates: list[Path] = []

    if paths is not None:
        for raw in paths:
            p = Path(raw).expanduser()
            if p not in candidates:
                candidates.append(p)

    env_value = os.environ.get("HEAVEN_PLUGIN_PATH")
    if env_value:
        for raw in env_value.split(os.pathsep):
            p = Path(raw).expanduser()
            if p not in candidates:
                candidates.append(p)

    local_dirs = [
        Path.cwd() / "heaven_plugins",
        Path.home() / ".heaven" / "plugins",
        Path.home() / ".config" / "heaven" / "plugins",
        Path(__file__).resolve().parent,
    ]
    for candidate in local_dirs:
        if candidate not in candidates:
            candidates.append(candidate)

    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def _load_module(path: Path) -> ModuleType:
    module_name = f"heaven_plugin_{abs(hash(str(path.resolve())))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to import plugin from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def demo_enabled() -> bool:
    """Bundled example plugins stay dormant unless explicitly switched on.

    `heaven/plugins/` is on the default discovery path, so without this the
    demo plugin would inject a synthetic finding into every real scan and a
    demo section into every markdown report.
    """

    return os.environ.get("HEAVEN_ENABLE_DEMO", "").strip().lower() in {"1", "true", "yes", "on"}


def _as_plugin_spec(module: ModuleType, source_path: Path) -> PluginSpec | None:
    plugin_data = getattr(module, "PLUGIN", None)
    if plugin_data is None:
        plugin_data = getattr(module, "plugin", None)

    if isinstance(plugin_data, dict):
        name = str(plugin_data.get("name") or source_path.stem.replace("_", "-"))
        description = str(plugin_data.get("description") or "No description provided")
        version = str(plugin_data.get("version") or "0.1.0")
        author = str(plugin_data.get("author") or "unknown")
        entry_point = str(plugin_data.get("entry_point") or "run")
        return PluginSpec(
            name=name,
            description=description,
            version=version,
            author=author,
            source=source_path.parent.name,
            path=str(source_path),
            entry_point=entry_point,
            module=module,
            raw=plugin_data,
        )

    if callable(plugin_data):
        name = getattr(plugin_data, "__name__", source_path.stem.replace("_", "-"))
        return PluginSpec(
            name=name,
            description=getattr(plugin_data, "__doc__", "Callable plugin") or "Callable plugin",
            version="0.1.0",
            author="unknown",
            source=source_path.parent.name,
            path=str(source_path),
            entry_point="__call__",
            module=module,
            raw={"callable": True},
        )

    callable_obj = getattr(module, "run", None)
    if callable(callable_obj):
        name = getattr(module, "PLUGIN_NAME", source_path.stem.replace("_", "-"))
        description = getattr(module, "PLUGIN_DESCRIPTION", "Built-in HEAVEN plugin")
        version = getattr(module, "PLUGIN_VERSION", "0.1.0")
        author = getattr(module, "PLUGIN_AUTHOR", "unknown")
        return PluginSpec(
            name=str(name),
            description=str(description),
            version=str(version),
            author=str(author),
            source=source_path.parent.name,
            path=str(source_path),
            entry_point="run",
            module=module,
            raw={},
        )

    return None


_CACHE_LIMIT = 8
_CACHE: dict[tuple[Any, ...], tuple[list[PluginSpec], list[PluginLoadError]]] = {}
_LAST_ERRORS: list[PluginLoadError] = []

# Discovery also walks this package's own directory, so the manager and the
# package init must be skipped explicitly: neither exports a plugin, and
# reporting them as broken plugin files would be pure noise.
_INTERNAL_FILES = {"__init__.py", Path(__file__).name}


def clear_plugin_cache() -> None:
    """Forget discovered plugins so the next call re-executes them."""

    global _LAST_ERRORS
    _CACHE.clear()
    _LAST_ERRORS = []


def plugin_load_errors() -> list[PluginLoadError]:
    """Files the most recent discovery could not load.

    Returns a copy; discovery keeps its own list so callers cannot mutate it.
    """

    return list(_LAST_ERRORS)


def _directory_signature(directories: Iterable[Path]) -> tuple[tuple[str, int, int], ...]:
    """Cheap fingerprint of every candidate plugin file.

    Hooks are called many times per scan, so re-importing modules on each call is
    wasteful and resets any module-level state. Keying the cache on mtime and size
    means an edited plugin is still picked up immediately.
    """

    entries: list[tuple[str, int, int]] = []
    for directory in directories:
        if not directory.exists() or not directory.is_dir():
            continue
        for plugin_file in sorted(directory.rglob("*.py")):
            try:
                stat = plugin_file.stat()
            except OSError:
                continue
            entries.append((str(plugin_file), stat.st_mtime_ns, stat.st_size))
    return tuple(entries)


def discover_plugins(paths: Iterable[str] | None = None) -> list[PluginSpec]:
    """Scan configured plugin directories and return discovered plugins.

    Files that fail to import are recorded in `plugin_load_errors()` rather than
    aborting discovery, so one broken plugin cannot hide every healthy one.
    """

    global _LAST_ERRORS

    directories = _candidate_directories(paths)
    cache_key = (demo_enabled(), _directory_signature(directories))
    cached = _CACHE.get(cache_key)
    if cached is not None:
        specs, errors = cached
        _LAST_ERRORS = list(errors)
        return list(specs)

    plugin_map: dict[str, PluginSpec] = {}
    errors: list[PluginLoadError] = []
    for directory in directories:
        if not directory.exists() or not directory.is_dir():
            continue

        for plugin_file in sorted(directory.rglob("*.py")):
            if plugin_file.name in _INTERNAL_FILES:
                continue
            if plugin_file.name.startswith("_"):
                continue
            try:
                module = _load_module(plugin_file)
            except Exception as exc:  # noqa: BLE001 — isolate one broken plugin
                logger.warning("Plugin %s failed to import: %s", plugin_file, exc)
                errors.append(
                    PluginLoadError(
                        path=str(plugin_file),
                        source=plugin_file.parent.name,
                        reason="import",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            spec = _as_plugin_spec(module, plugin_file)
            if spec is None:
                errors.append(
                    PluginLoadError(
                        path=str(plugin_file),
                        source=plugin_file.parent.name,
                        reason="no-entry-point",
                        error="no PLUGIN dict, plugin callable, or run() function",
                    )
                )
                continue
            if spec.raw.get("demo") and not demo_enabled():
                continue
            plugin_map.setdefault(spec.name, spec)

    specs = sorted(plugin_map.values(), key=lambda spec: spec.name.lower())
    # Bound the cache: a stale signature can never be reached again once its
    # files changed, so unlimited growth would leak memory in long-lived
    # processes such as the API server. A handful of entries still keeps
    # alternating callers (bundled paths vs HEAVEN_PLUGIN_PATH) from thrashing.
    while len(_CACHE) >= _CACHE_LIMIT:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[cache_key] = (specs, errors)
    _LAST_ERRORS = list(errors)
    return list(specs)


def load_plugin(name: str, paths: Iterable[str] | None = None) -> PluginSpec:
    """Load and return a plugin by name."""

    for plugin in discover_plugins(paths):
        if plugin.name == name:
            return plugin
    raise LookupError(f"Plugin '{name}' not found")


def run_plugin(name: str, **kwargs: Any) -> Any:
    """Invoke a plugin by name with keyword arguments."""

    plugin = load_plugin(name)
    func = None
    if plugin.module is not None:
        if isinstance(plugin.raw, dict) and plugin.entry_point in plugin.raw:
            func = getattr(plugin.module, plugin.entry_point, None)
        else:
            func = getattr(plugin.module, plugin.entry_point, None)
        if func is None and hasattr(plugin.module, "run"):
            func = plugin.module.run
    if func is None:
        raise TypeError(f"Plugin '{name}' does not define a callable entry point")
    return func(**kwargs)


def call_hook(hook_name: str, **kwargs: Any) -> list[dict[str, Any]]:
    """Run every plugin hook matching a lifecycle name.

    A plugin may export a method named ``hook_<name>`` and receive the same
    keyword arguments as the lifecycle trigger. This lets scan phases, report
    generation, and post-processing accumulate plugin results without hardcoding
    extension points in the core engine.
    """

    results: list[dict[str, Any]] = []
    for plugin in discover_plugins():
        if plugin.module is None:
            continue
        hook = getattr(plugin.module, f"hook_{hook_name}", None)
        if not callable(hook):
            continue
        try:
            payload = hook(**kwargs)
        except Exception as exc:  # pragma: no cover - plugin failures are isolated
            results.append({"plugin": plugin.name, "hook": hook_name, "status": "error", "error": str(exc)})
            continue
        results.append({"plugin": plugin.name, "hook": hook_name, "status": "ok", "result": payload})
    return results


def enrich_findings(findings: list[dict[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
    """Run all plugin finding-enrichment hooks.

    A plugin may provide ``hook_enrich_findings`` and return either a list of
    finding dicts or a dict with a ``findings`` key. The merged list is returned
    so the orchestrator can fold plugin-produced evidence into the core result set.
    """

    enriched: list[dict[str, Any]] = list(findings)
    for plugin in discover_plugins():
        if plugin.module is None:
            continue
        hook = getattr(plugin.module, "hook_enrich_findings", None)
        if not callable(hook):
            continue
        try:
            payload = hook(findings=list(findings), **kwargs)
        except Exception:
            continue
        if isinstance(payload, dict):
            next_findings = payload.get("findings", [])
            if isinstance(next_findings, list):
                enriched.extend(next_findings)
        elif isinstance(payload, list):
            enriched.extend(payload)
    return enriched


def get_report_sections(summary: dict[str, Any], **kwargs: Any) -> list[dict[str, Any]]:
    """Collect plugin-defined markdown- or JSON-friendly report sections."""

    sections: list[dict[str, Any]] = []
    for plugin in discover_plugins():
        if plugin.module is None:
            continue
        hook = getattr(plugin.module, "hook_report", None)
        if not callable(hook):
            continue
        try:
            payload = hook(summary=summary, **kwargs)
        except Exception:
            continue
        if isinstance(payload, dict):
            sections.append(payload)
        elif isinstance(payload, list):
            sections.extend(item for item in payload if isinstance(item, dict))
    return sections
