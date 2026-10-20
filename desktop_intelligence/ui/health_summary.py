"""Summariser and status aggregator for background collectors and diagnostics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
from desktop_intelligence.collectors.base import CollectorHealth


@dataclass
class HealthSummary:
    """Consolidated health report across all collectors."""
    overall_status: str       # "Operational (Active)", "Degraded (Polling)", "Failed", "Unavailable", "Stopped"
    severity: str             # "ok" | "warning" | "error"
    badge_color: str          # Hex color suitable for status badge
    summary_text: str         # High-level one-line summary
    is_degraded_or_failed: bool
    collectors: List[CollectorHealth]
    primary_remediation: Optional[str] = None


def summarise_health(health_dict: Optional[Dict[str, CollectorHealth]]) -> HealthSummary:
    """Evaluate collector health dictionary into consolidated diagnostic summary."""
    if not health_dict:
        return HealthSummary(
            overall_status="Stopped",
            severity="ok",
            badge_color="#94A3B8",
            summary_text="All background collection services are stopped.",
            is_degraded_or_failed=False,
            collectors=[],
            primary_remediation=None,
        )

    collectors = list(health_dict.values())
    states = [c.state for c in collectors]
    severities = [c.severity for c in collectors]

    has_failed = any(s in ("failed", "unavailable") for s in states) or "error" in severities
    has_degraded = any(s == "degraded" for s in states) or "warning" in severities
    all_active = all(s == "active" for s in states if s != "disabled")

    if has_failed:
        overall_status = "Failed" if any(s == "failed" for s in states) else "Unavailable"
        severity = "error"
        badge_color = "#FB7185"
        failed_cols = [c for c in collectors if c.state in ("failed", "unavailable") or c.severity == "error"]
        reasons = [c.reason or c.message for c in failed_cols if c.reason or c.message]
        summary_text = f"Collector failure: {reasons[0]}" if reasons else "One or more collectors failed."
        remediations = [c.remediation for c in failed_cols if c.remediation]
        primary_remediation = remediations[0] if remediations else "Inspect system permissions and event logs."
        is_degraded_or_failed = True
    elif has_degraded:
        overall_status = "Degraded (Polling)"
        severity = "warning"
        badge_color = "#FBBF24"
        degraded_cols = [c for c in collectors if c.state == "degraded" or c.severity == "warning"]
        reasons = [c.reason or c.message for c in degraded_cols if c.reason or c.message]
        summary_text = f"Degraded collection: {reasons[0]}" if reasons else "Collectors operational in degraded polling mode."
        remediations = [c.remediation for c in degraded_cols if c.remediation]
        primary_remediation = remediations[0] if remediations else "Run as Administrator for full kernel trace access."
        is_degraded_or_failed = True
    elif all_active:
        overall_status = "Operational (Active)"
        severity = "ok"
        badge_color = "#34D399"
        summary_text = "All event listeners and hooks are active and recording events."
        primary_remediation = None
        is_degraded_or_failed = False
    elif any(s == "stopped" for s in states):
        overall_status = "Stopped"
        severity = "ok"
        badge_color = "#94A3B8"
        summary_text = "Background event monitoring is currently stopped."
        primary_remediation = None
        is_degraded_or_failed = False
    else:
        overall_status = "Operational"
        severity = "ok"
        badge_color = "#34D399"
        summary_text = "System collectors operational."
        primary_remediation = None
        is_degraded_or_failed = False

    return HealthSummary(
        overall_status=overall_status,
        severity=severity,
        badge_color=badge_color,
        summary_text=summary_text,
        is_degraded_or_failed=is_degraded_or_failed,
        collectors=collectors,
        primary_remediation=primary_remediation,
    )
