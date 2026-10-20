"""Launch pattern detection with strict observation periods and context occurrence thresholds."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from typing import Dict, List, Optional, Set
import numpy as np
import pandas as pd

from desktop_intelligence.config import PatternsConfig

logger = logging.getLogger(__name__)

WEEKDAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday"}
WEEKENDS = {"Saturday", "Sunday"}


@dataclass
class LaunchPattern:
    app_name: str
    day_of_week: str
    time_bucket: str
    day_type: str  # "weekday" or "weekend"
    frequency: float
    launches_in_context: int
    context_occurrences: int
    total_observation_days: int
    is_habit: bool
    evidence: dict


def detect_launch_patterns(
    sessions_df: pd.DataFrame,
    config: Optional[PatternsConfig] = None,
) -> List[LaunchPattern]:
    """Detect recurring application launch habits using mathematically strict denominators.

    Requirements:
    1. Total observation period >= config.minimum_observation_days (default 14).
    2. Context occurrences (eligible matching days) >= config.minimum_context_occurrences (default 10).
    3. Frequency (launches in context / eligible matching days) >= config.launch_frequency_threshold (default 0.80).
    4. Day type matches eligible_day_types.
    """
    if sessions_df is None or sessions_df.empty:
        return []

    cfg = config or PatternsConfig()

    # Determine observation date span
    dates = pd.to_datetime(sessions_df["local_date"], errors="coerce").dropna()
    if dates.empty:
        return []

    min_date = dates.min()
    max_date = dates.max()
    total_observation_days = (max_date - min_date).days + 1

    # Check 1: Minimum observation period gate
    if total_observation_days < cfg.minimum_observation_days:
        logger.debug(
            "Observation span %d days is less than required %d days; no habits learned.",
            total_observation_days,
            cfg.minimum_observation_days,
        )
        return []

    # Map each distinct date to its day of week and day type
    all_observed_dates = sessions_df[["local_date", "day_of_week"]].drop_duplicates()
    all_observed_dates["day_type"] = all_observed_dates["day_of_week"].apply(
        lambda d: "weekday" if d in WEEKDAYS else "weekend"
    )

    # Filter by eligible day types
    eligible_day_types = set(cfg.eligible_day_types)
    all_observed_dates = all_observed_dates[all_observed_dates["day_type"].isin(eligible_day_types)]

    # Count distinct observed dates per (day_of_week, day_type)
    context_date_counts: Dict[str, Set[str]] = {}
    for _, row in all_observed_dates.iterrows():
        dow = str(row["day_of_week"])
        dt_str = str(row["local_date"])
        context_date_counts.setdefault(dow, set()).add(dt_str)

    patterns: List[LaunchPattern] = []

    # Group sessions by (day_of_week, time_bucket, process_name)
    # Each row contributes to active usage on that local_date
    grouped = sessions_df.groupby(["day_of_week", "time_bucket", "process_name"])

    for (dow, time_b, app_name), group in grouped:
        dow_str = str(dow)
        time_b_str = str(time_b)
        app_str = str(app_name)

        day_type = "weekday" if dow_str in WEEKDAYS else "weekend"
        if day_type not in eligible_day_types:
            continue

        # Denominator: total distinct observed days for this day_of_week
        eligible_dates = context_date_counts.get(dow_str, set())
        context_occurrences = len(eligible_dates)

        # Check 2: Minimum context occurrences gate
        if context_occurrences < cfg.minimum_context_occurrences:
            continue

        # Numerator: distinct dates in this context where this app was launched
        app_launch_dates = set(group["local_date"].dropna().unique())
        # Intersect with eligible dates
        matching_launch_dates = app_launch_dates.intersection(eligible_dates)
        launches_in_context = len(matching_launch_dates)

        frequency = float(launches_in_context) / float(context_occurrences)

        # Check 3: Launch frequency threshold
        is_habit = frequency >= cfg.launch_frequency_threshold

        evidence = {
            "app_name": app_str,
            "day_of_week": dow_str,
            "time_bucket": time_b_str,
            "day_type": day_type,
            "frequency": round(frequency, 4),
            "frequency_percent": round(frequency * 100.0, 1),
            "launches_in_context": launches_in_context,
            "context_occurrences": context_occurrences,
            "total_observation_days": total_observation_days,
            "threshold": cfg.launch_frequency_threshold,
        }

        pattern = LaunchPattern(
            app_name=app_str,
            day_of_week=dow_str,
            time_bucket=time_b_str,
            day_type=day_type,
            frequency=round(frequency, 4),
            launches_in_context=launches_in_context,
            context_occurrences=context_occurrences,
            total_observation_days=total_observation_days,
            is_habit=is_habit,
            evidence=evidence,
        )

        if is_habit:
            patterns.append(pattern)

    # Sort habits by frequency descending, then context occurrences descending
    patterns.sort(key=lambda x: (-x.frequency, -x.context_occurrences))
    return patterns
