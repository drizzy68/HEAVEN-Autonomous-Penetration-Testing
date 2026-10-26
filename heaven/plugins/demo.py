"""Example HEAVEN plugin.

This is intentionally small and safe; it is meant to demonstrate the plugin API
and show how external modules can safely enrich HEAVEN without touching the core
scan pipeline.

It is dormant by default: set ``HEAVEN_ENABLE_DEMO=1`` to load it. Its hooks add
synthetic evidence, so it must never run during a real scan unrehearsed.
"""

from __future__ import annotations

PLUGIN = {
    "name": "demo",
    "description": "Example plugin that summarizes a target for a scan workflow.",
    "version": "0.1.0",
    "author": "HEAVEN",
    "entry_point": "run",
    "demo": True,
}


def run(
    target: str | None = None,
    *,
    mode: str = "summary",
    tags: list[str] | None = None,
    summary: dict[str, object] | None = None,
    targets: dict[str, object] | None = None,
    engagement: str | None = None,
    **kwargs,
) -> dict[str, object]:
    """Return a tiny summary payload for a target.

    Real plugins can call `heaven` modules, do recon, or produce report metadata.
    """

    resolved_target = target or (targets.get("urls") or targets.get("ips") or ["unknown"])[0]
    evidence_count = len(summary.get("vulnerabilities", [])) if isinstance(summary, dict) else 0

    return {
        "status": "ok",
        "plugin": "demo",
        "target": resolved_target,
        "mode": mode,
        "tags": tags or [],
        "engagement": engagement,
        "summary": f"Target {resolved_target} is ready for a HEAVEN scan workflow.",
        "finding_count": evidence_count,
        "extra": kwargs,
    }


def hook_after_scan(
    *,
    scan_id: str | None = None,
    mode: str | None = None,
    targets: dict[str, object] | None = None,
    results: list[object] | None = None,
    **kwargs,
) -> dict[str, object]:
    """Lifecycle hook invoked once, by the orchestrator, after a scan completes.

    The orchestrator owns this hook and passes the raw task results; the CLI does
    not fire it a second time.
    """

    urls = (targets or {}).get("urls") or (targets or {}).get("ips") or ["unknown"]
    return {
        "plugin": "demo",
        "hook": "after_scan",
        "scan_id": scan_id,
        "mode": mode,
        "target": urls[0],
        "evidence_count": len(results or []),
        "status": "post_scan_hook_ok",
    }


def hook_before_phase_recon(*, phase: str | None = None, targets: dict[str, object] | None = None, **kwargs) -> dict[str, object]:
    """Example hook for a specific orchestrator phase."""

    return {
        "plugin": "demo",
        "hook": "before_phase_recon",
        "phase": phase,
        "target_count": len((targets or {}).get("urls", []) or (targets or {}).get("ips", []) or []),
        "status": "recon_hook_ok",
    }


def hook_after_phase_recon(*, phase: str | None = None, results: list[object] | None = None, **kwargs) -> dict[str, object]:
    """Example hook for phase completion events."""

    return {
        "plugin": "demo",
        "hook": "after_phase_recon",
        "phase": phase,
        "result_count": len(results or []),
        "status": "phase_hook_ok",
    }


def hook_enrich_findings(*, findings: list[dict[str, object]] | None = None, **kwargs) -> dict[str, object]:
    """Inject plugin-owned findings into the result stream."""

    items = findings or []
    if not items:
        return {"findings": []}

    return {
        "findings": [{
            "target": "plugin:demo",
            "vuln_type": "reporting_plugin_evidence",
            "severity": "info",
            "confidence": 0.35,
            "title": "Plugin-added evidence record",
            "description": "This finding was injected by the example HEAVEN plugin to demonstrate finding enrichment.",
            "plugin": "demo",
        }]
    }


def hook_report(*, summary: dict[str, object] | None = None, target: str | None = None, **kwargs) -> dict[str, object]:
    """Return a plugin-defined report section for Markdown / JSON output."""

    return {
        "title": "Plugin: Demo Summary",
        "content": f"Demonstration plugin attached for target {target or 'unknown'} with {len((summary or {}).get('vulnerabilities', []) or [])} vulns in the summary.",
        "name": "demo_summary",
    }
