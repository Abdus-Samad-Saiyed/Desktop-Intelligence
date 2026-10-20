"""Data cleaning and type normalization using Pandas and NumPy."""

import numpy as np
import pandas as pd
from typing import List

from desktop_intelligence.models import SCHEMAS


def clean_sessions_df(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and normalize activity sessions DataFrame."""
    if df is None or df.empty:
        return pd.DataFrame(columns=SCHEMAS["activity_sessions"])

    cleaned = df.copy()

    # Ensure required columns exist
    for col in SCHEMAS["activity_sessions"]:
        if col not in cleaned.columns:
            cleaned[col] = np.nan

    # Drop duplicate session IDs
    cleaned = cleaned.drop_duplicates(subset=["session_id"], keep="first")

    # Clean string columns
    cleaned["process_name"] = cleaned["process_name"].astype(str).str.strip()
    cleaned = cleaned[cleaned["process_name"].str.len() > 0]
    cleaned = cleaned[~cleaned["process_name"].isin(["nan", "None", "unknown"])]

    # Parse and validate timestamps
    cleaned["start_dt"] = pd.to_datetime(cleaned["start_ts_utc"], utc=True, errors="coerce")
    cleaned["end_dt"] = pd.to_datetime(cleaned["end_ts_utc"], utc=True, errors="coerce")
    cleaned = cleaned.dropna(subset=["start_dt", "end_dt"])

    # Parse numeric durations
    cleaned["duration_seconds"] = pd.to_numeric(cleaned["duration_seconds"], errors="coerce")
    cleaned["idle_seconds"] = pd.to_numeric(cleaned["idle_seconds"], errors="coerce").fillna(0.0)
    cleaned = cleaned.dropna(subset=["duration_seconds"])

    # Discard negative durations or inverted timestamps
    cleaned = cleaned[cleaned["duration_seconds"] >= 0]
    cleaned = cleaned[cleaned["end_dt"] >= cleaned["start_dt"]]

    # Ensure active duration (duration - idle) is not negative
    cleaned["active_seconds"] = np.maximum(0.0, cleaned["duration_seconds"] - cleaned["idle_seconds"])

    # Sort chronologically by start timestamp
    cleaned = cleaned.sort_values(by="start_dt").reset_index(drop=True)
    return cleaned


def clean_samples_df(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and normalize resource samples DataFrame."""
    if df is None or df.empty:
        return pd.DataFrame(columns=SCHEMAS["resource_samples"])

    cleaned = df.copy()

    for col in SCHEMAS["resource_samples"]:
        if col not in cleaned.columns:
            cleaned[col] = np.nan

    cleaned = cleaned.drop_duplicates(subset=["sample_id"], keep="first")

    cleaned["sample_dt"] = pd.to_datetime(cleaned["sample_ts_utc"], utc=True, errors="coerce")
    cleaned = cleaned.dropna(subset=["sample_dt"])

    cleaned["process_name"] = cleaned["process_name"].astype(str).str.strip()
    cleaned["pid"] = pd.to_numeric(cleaned["pid"], errors="coerce").fillna(0).astype(int)

    cleaned["rss_bytes"] = pd.to_numeric(cleaned["rss_bytes"], errors="coerce")
    cleaned["process_memory_percent"] = pd.to_numeric(cleaned["process_memory_percent"], errors="coerce")
    cleaned["cpu_time_seconds"] = pd.to_numeric(cleaned["cpu_time_seconds"], errors="coerce")
    cleaned["system_memory_percent"] = pd.to_numeric(cleaned["system_memory_percent"], errors="coerce")

    # Sanitize percentages
    cleaned.loc[cleaned["process_memory_percent"] < 0, "process_memory_percent"] = np.nan
    cleaned.loc[cleaned["process_memory_percent"] > 100, "process_memory_percent"] = 100.0

    cleaned.loc[cleaned["system_memory_percent"] < 0, "system_memory_percent"] = np.nan
    cleaned.loc[cleaned["system_memory_percent"] > 100, "system_memory_percent"] = 100.0

    cleaned = cleaned.sort_values(by="sample_dt").reset_index(drop=True)
    return cleaned


def clean_events_df(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and normalize activity events DataFrame."""
    if df is None or df.empty:
        return pd.DataFrame(columns=SCHEMAS["activity_events"])

    cleaned = df.copy()

    for col in SCHEMAS["activity_events"]:
        if col not in cleaned.columns:
            cleaned[col] = np.nan

    cleaned = cleaned.drop_duplicates(subset=["event_id"], keep="first")

    cleaned["event_dt"] = pd.to_datetime(cleaned["event_ts_utc"], utc=True, errors="coerce")
    cleaned = cleaned.dropna(subset=["event_dt"])

    cleaned["process_name"] = cleaned["process_name"].astype(str).str.strip()
    cleaned["pid"] = pd.to_numeric(cleaned["pid"], errors="coerce").fillna(0).astype(int)
    cleaned["event_type"] = cleaned["event_type"].astype(str).str.strip()

    cleaned = cleaned.sort_values(by="event_dt").reset_index(drop=True)
    return cleaned
