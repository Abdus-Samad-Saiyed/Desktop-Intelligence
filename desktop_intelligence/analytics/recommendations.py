"""Recommendation generator synthesizing patterns, resource hogs, and inventory findings."""

from datetime import datetime, timezone, timedelta
import json
import logging
from typing import Dict, List, Optional, Set
import pandas as pd

from desktop_intelligence.analytics.patterns import LaunchPattern, detect_launch_patterns
from desktop_intelligence.analytics.resources import ResourceHogFinding, analyze_resource_hogs
from desktop_intelligence.collectors.base import Clock, SystemClock
from desktop_intelligence.config import AppConfig
from desktop_intelligence.models import (
    InventoryItem,
    RecommendationRecord,
    format_utc_iso,
    parse_utc_iso,
    new_id,
)
from desktop_intelligence.storage.csv_store import CsvStore

logger = logging.getLogger(__name__)


def generate_recommendations(
    config: AppConfig,
    store: CsvStore,
    sessions_df: pd.DataFrame,
    samples_df: pd.DataFrame,
    inventory_items: Optional[List[InventoryItem]] = None,
    clock: Optional[Clock] = None,
) -> List[RecommendationRecord]:
    """Generate evidence-backed recommendations with duplicate prevention and cooldown."""
    clk = clock or SystemClock()
    now_ts = format_utc_iso(clk.now_utc())
    cooldown_cutoff = clk.now_utc() - timedelta(days=7)

    # Read existing recommendations to prevent duplicate pending recommendations and respect cooldown
    existing_rows = store.read_rows("recommendations", store.paths.recommendations_csv)
    existing_signatures: Set[str] = set()
    for r in existing_rows:
        status = r.get("status", "")
        sig = f"{r.get('category')}::{r.get('subject')}"
        if status in {"pending", "approved"}:
            existing_signatures.add(sig)
        elif status in {"declined", "dismissed", "rejected"}:
            try:
                ts_str = r.get("updated_ts_utc") or r.get("created_ts_utc", "")
                c_dt = parse_utc_iso(ts_str)
                if c_dt > cooldown_cutoff:
                    existing_signatures.add(sig)
            except Exception:
                existing_signatures.add(sig)

    new_recommendations: List[RecommendationRecord] = []

    # 1. Habit Launch Recommendations
    patterns = detect_launch_patterns(sessions_df, config.patterns)
    for p in patterns:
        subject = f"Launch {p.app_name} on {p.day_of_week} at {p.time_bucket}"
        sig = f"habit_launch::{subject}"
        if sig in existing_signatures:
            continue

        rec = RecommendationRecord(
            recommendation_id=new_id("rec"),
            created_ts_utc=now_ts,
            category="habit_launch",
            subject=subject,
            evidence_json=json.dumps(p.evidence, sort_keys=True),
            confidence=round(p.frequency, 2),
            status="pending",
        )
        new_recommendations.append(rec)
        existing_signatures.add(sig)

    # 2. Resource Hog Recommendations
    hogs = analyze_resource_hogs(samples_df, config.resources)
    for h in hogs:
        if not h.is_hog:
            continue

        subject = f"High memory consumption in {h.process_name}"
        sig = f"resource_hog::{subject}"
        if sig in existing_signatures:
            continue

        evidence = {
            "process_name": h.process_name,
            "max_memory_percent": h.max_memory_percent,
            "avg_memory_percent": h.avg_memory_percent,
            "max_rss_bytes": h.max_rss_bytes,
            "sustained_samples": h.sustained_samples,
            "reason": h.reason,
        }

        confidence = round(min(1.0, max(0.5, h.max_memory_percent / 100.0)), 2)
        rec = RecommendationRecord(
            recommendation_id=new_id("rec"),
            created_ts_utc=now_ts,
            category="resource_hog",
            subject=subject,
            evidence_json=json.dumps(evidence, sort_keys=True),
            confidence=confidence,
            status="pending",
        )
        new_recommendations.append(rec)
        existing_signatures.add(sig)

    # 3. Unused Application Recommendations
    # Only propose if observation span >= minimum_observation_days
    if inventory_items and not sessions_df.empty:
        dates = pd.to_datetime(sessions_df["local_date"], errors="coerce").dropna()
        if not dates.empty:
            total_days = (dates.max() - dates.min()).days + 1
            if total_days >= config.patterns.minimum_observation_days:
                unused_items = [it for it in inventory_items if it.observed_launch_count == 0]
                if len(unused_items) > 3:
                    subject = f"Review {len(unused_items)} unused applications"
                    sig = f"unused_application::{subject}"
                    if sig not in existing_signatures:
                        evidence = {
                            "unused_count": len(unused_items),
                            "sample_apps": [it.display_name for it in unused_items[:10]],
                            "observation_days": total_days,
                            "label": f"{len(unused_items)} installed applications have not been launched during monitoring.",
                        }
                        rec = RecommendationRecord(
                            recommendation_id=new_id("rec"),
                            created_ts_utc=now_ts,
                            category="unused_application",
                            subject=subject,
                            evidence_json=json.dumps(evidence, sort_keys=True),
                            confidence=0.75,
                            status="pending",
                        )
                        new_recommendations.append(rec)
                        existing_signatures.add(sig)
                elif len(unused_items) > 0:
                    for item in unused_items:
                        subject = f"Application not observed in use: {item.display_name}"
                        sig = f"unused_application::{subject}"
                        if sig in existing_signatures:
                            continue

                        evidence = {
                            "display_name": item.display_name,
                            "exe_path": item.exe_path,
                            "inventory_source": item.inventory_source,
                            "first_seen_ts_utc": item.first_seen_ts_utc,
                            "observation_days": total_days,
                            "label": "Not observed since monitoring began",
                        }

                        rec = RecommendationRecord(
                            recommendation_id=new_id("rec"),
                            created_ts_utc=now_ts,
                            category="unused_application",
                            subject=subject,
                            evidence_json=json.dumps(evidence, sort_keys=True),
                            confidence=0.75,
                            status="pending",
                        )
                        new_recommendations.append(rec)
                        existing_signatures.add(sig)

    # Persist new recommendations to CSV
    for rec in new_recommendations:
        store.append_recommendation(rec)

    return new_recommendations
