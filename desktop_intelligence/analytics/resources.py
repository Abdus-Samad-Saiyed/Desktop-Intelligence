"""Resource consumption analysis and outlier/hog detection."""

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

from desktop_intelligence.config import ResourcesConfig


@dataclass
class ResourceHogFinding:
    process_name: str
    sustained_samples: int
    max_memory_percent: float
    avg_memory_percent: float
    max_rss_bytes: int
    is_hog: bool
    reason: str
    total_samples: int = 0
    exceedance_samples: int = 0
    observation_span_seconds: float = 0.0


def analyze_resource_hogs(
    samples_df: pd.DataFrame,
    config: Optional[ResourcesConfig] = None,
) -> List[ResourceHogFinding]:
    """Identify applications with sustained high memory or system pressure."""
    if samples_df is None or samples_df.empty:
        return []

    cfg = config or ResourcesConfig()
    threshold = cfg.high_memory_percent
    min_count = cfg.sustained_observation_count

    findings: List[ResourceHogFinding] = []

    for app_name, group in samples_df.groupby("process_name"):
        mem_series = group["process_memory_percent"].dropna()
        if mem_series.empty:
            continue

        mem_arr = mem_series.to_numpy(dtype=np.float64)
        total_samples = len(mem_arr)
        over_threshold_mask = mem_arr >= threshold
        over_count = int(np.sum(over_threshold_mask))

        max_mem = float(np.max(mem_arr))
        avg_mem = float(np.mean(mem_arr))

        rss_series = group["rss_bytes"].dropna()
        max_rss = int(rss_series.max()) if not rss_series.empty else 0

        # Calculate time span if timestamp column available
        span_seconds = 0.0
        ts_col = "sample_ts_utc" if "sample_ts_utc" in group.columns else ("timestamp_utc" if "timestamp_utc" in group.columns else None)
        if ts_col:
            ts_series = pd.to_datetime(group[ts_col].dropna(), errors="coerce")
            if len(ts_series) >= 2:
                span_seconds = max(0.0, float((ts_series.max() - ts_series.min()).total_seconds()))

        is_hog = over_count >= min_count
        if is_hog:
            reason = (
                f"Process exceeded memory threshold of {threshold:.1f}% in {over_count} of {total_samples} "
                f"observations (max: {max_mem:.1f}%)."
            )
        else:
            reason = f"Normal consumption: {over_count} of {total_samples} observations exceeded {threshold:.1f}% (max: {max_mem:.1f}%)."

        findings.append(
            ResourceHogFinding(
                process_name=app_name,
                sustained_samples=over_count,
                max_memory_percent=round(max_mem, 1),
                avg_memory_percent=round(avg_mem, 1),
                max_rss_bytes=max_rss,
                is_hog=is_hog,
                reason=reason,
                total_samples=total_samples,
                exceedance_samples=over_count,
                observation_span_seconds=span_seconds,
            )
        )

    # Sort so hogs appear first, then by max memory percent descending
    findings.sort(key=lambda x: (not x.is_hog, -x.max_memory_percent))
    return findings
