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
        over_threshold_mask = mem_arr >= threshold
        over_count = int(np.sum(over_threshold_mask))

        max_mem = float(np.max(mem_arr))
        avg_mem = float(np.mean(mem_arr))

        rss_series = group["rss_bytes"].dropna()
        max_rss = int(rss_series.max()) if not rss_series.empty else 0

        is_hog = over_count >= min_count
        if is_hog:
            reason = (
                f"Process exceeded memory threshold of {threshold:.1f}% across {over_count} "
                f"distinct observations (max: {max_mem:.1f}%)."
            )
        else:
            reason = f"Normal consumption within threshold (max: {max_mem:.1f}%)."

        findings.append(
            ResourceHogFinding(
                process_name=app_name,
                sustained_samples=over_count,
                max_memory_percent=round(max_mem, 1),
                avg_memory_percent=round(avg_mem, 1),
                max_rss_bytes=max_rss,
                is_hog=is_hog,
                reason=reason,
            )
        )

    # Sort so hogs appear first, then by max memory percent descending
    findings.sort(key=lambda x: (not x.is_hog, -x.max_memory_percent))
    return findings
