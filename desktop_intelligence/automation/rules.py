"""Automation rule definitions and synchronization from approved recommendations."""

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from desktop_intelligence.models import InventoryItem, RecommendationRecord

logger = logging.getLogger(__name__)


@dataclass
class AutomationRule:
    rule_id: str
    app_name: str
    exe_path: str
    day_of_week: str
    time_bucket: str
    frequency_percent: float
    approved: bool
    enabled: bool = True
    last_triggered_date: str = ""


def sync_rules_from_recommendations(
    recommendations: List[RecommendationRecord],
    inventory_items: Optional[List[InventoryItem]] = None,
    exe_path_map: Optional[Dict[str, str]] = None,
) -> List[AutomationRule]:
    """Convert approved habit_launch recommendations into actionable automation rules."""
    path_lookup: Dict[str, str] = {}

    if inventory_items:
        for item in inventory_items:
            if item.exe_path:
                path_lookup[item.display_name.lower()] = item.exe_path
                exe_name = Path(item.exe_path).name.lower()
                path_lookup[exe_name] = item.exe_path

    if exe_path_map:
        for k, v in exe_path_map.items():
            path_lookup[k.lower()] = v

    rules: List[AutomationRule] = []

    for rec in recommendations:
        if rec.category != "habit_launch":
            continue

        try:
            ev = json.loads(rec.evidence_json)
        except Exception:
            continue

        app_name = ev.get("app_name", "").strip()
        day_of_week = ev.get("day_of_week", "").strip()
        time_bucket = ev.get("time_bucket", "").strip()
        freq_pct = float(ev.get("frequency_percent", rec.confidence * 100.0))

        # Resolve executable path
        resolved_exe = path_lookup.get(app_name.lower(), "")
        if not resolved_exe:
            # Check if app_name itself is an executable path
            if os.path.isabs(app_name) and os.path.exists(app_name):
                resolved_exe = app_name

        rule = AutomationRule(
            rule_id=rec.recommendation_id,
            app_name=app_name,
            exe_path=resolved_exe,
            day_of_week=day_of_week,
            time_bucket=time_bucket,
            frequency_percent=freq_pct,
            approved=(rec.status == "approved"),
            enabled=True,
        )
        rules.append(rule)

    return rules
