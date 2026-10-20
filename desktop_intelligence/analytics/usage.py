"""Usage statistics, grouping, aggregations, and NumPy baseline calculations."""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple

DAYS_OF_WEEK_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def calculate_usage_summary(sessions_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate total usage per application across all observed sessions."""
    if sessions_df is None or sessions_df.empty:
        return pd.DataFrame(columns=[
            "process_name", "total_hours", "active_hours", "idle_hours",
            "session_count", "avg_session_min", "median_session_min", "pct_active_time"
        ])

    grouped = sessions_df.groupby("process_name")

    agg_df = grouped.agg(
        total_seconds=("duration_seconds", "sum"),
        active_seconds=("active_seconds", "sum"),
        idle_seconds=("idle_seconds", "sum"),
        session_count=("session_id", "count"),
        avg_session_sec=("duration_seconds", "mean"),
        median_session_sec=("duration_seconds", "median"),
    ).reset_index()

    total_active_all = agg_df["active_seconds"].sum()

    # Vectorized conversion using NumPy
    agg_df["total_hours"] = np.round(agg_df["total_seconds"] / 3600.0, 2)
    agg_df["active_hours"] = np.round(agg_df["active_seconds"] / 3600.0, 2)
    agg_df["idle_hours"] = np.round(agg_df["idle_seconds"] / 3600.0, 2)
    agg_df["avg_session_min"] = np.round(agg_df["avg_session_sec"] / 60.0, 1)
    agg_df["median_session_min"] = np.round(agg_df["median_session_sec"] / 60.0, 1)

    if total_active_all > 0:
        agg_df["pct_active_time"] = np.round((agg_df["active_seconds"] / total_active_all) * 100.0, 1)
    else:
        agg_df["pct_active_time"] = 0.0

    cols = [
        "process_name", "total_hours", "active_hours", "idle_hours",
        "session_count", "avg_session_min", "median_session_min", "pct_active_time"
    ]
    return agg_df[cols].sort_values(by="active_hours", ascending=False).reset_index(drop=True)


def calculate_daily_summary(sessions_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate daily total active and idle hours."""
    if sessions_df is None or sessions_df.empty:
        return pd.DataFrame(columns=["local_date", "active_hours", "idle_hours", "total_hours", "session_count"])

    grouped = sessions_df.groupby("local_date")
    daily = grouped.agg(
        active_sec=("active_seconds", "sum"),
        idle_sec=("idle_seconds", "sum"),
        total_sec=("duration_seconds", "sum"),
        session_count=("session_id", "count"),
    ).reset_index()

    daily["active_hours"] = np.round(daily["active_sec"] / 3600.0, 2)
    daily["idle_hours"] = np.round(daily["idle_sec"] / 3600.0, 2)
    daily["total_hours"] = np.round(daily["total_sec"] / 3600.0, 2)

    return daily[["local_date", "active_hours", "idle_hours", "total_hours", "session_count"]].sort_values("local_date").reset_index(drop=True)


def calculate_day_of_week_distribution(sessions_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate active hours per day of the week in standard order."""
    if sessions_df is None or sessions_df.empty:
        return pd.DataFrame({"day_of_week": DAYS_OF_WEEK_ORDER, "active_hours": [0.0] * 7})

    dow_grouped = sessions_df.groupby("day_of_week")["active_seconds"].sum()
    hours_map = (dow_grouped / 3600.0).to_dict()

    data = [{"day_of_week": d, "active_hours": round(hours_map.get(d, 0.0), 2)} for d in DAYS_OF_WEEK_ORDER]
    return pd.DataFrame(data)


def calculate_hourly_heatmap_matrix(sessions_df: pd.DataFrame) -> np.ndarray:
    """Create a 7x24 NumPy matrix of total active minutes (7 days of week x 24 hours of day).

    Accurately distributes multi-hour session active durations across their respective hourly buckets.
    """
    matrix = np.zeros((7, 24), dtype=np.float64)
    if sessions_df is None or sessions_df.empty:
        return matrix

    dow_index = {d: i for i, d in enumerate(DAYS_OF_WEEK_ORDER)}

    start_col = "start_dt" if "start_dt" in sessions_df.columns else ("start_ts_utc" if "start_ts_utc" in sessions_df.columns else None)
    end_col = "end_dt" if "end_dt" in sessions_df.columns else ("end_ts_utc" if "end_ts_utc" in sessions_df.columns else None)

    for _, row in sessions_df.iterrows():
        dow = str(row.get("day_of_week", "")).strip()
        active_sec = float(row.get("active_seconds", 0.0))
        if active_sec <= 0:
            continue

        if dow not in dow_index:
            continue

        r_idx = dow_index[dow]

        # Slicing across hours if start/end timestamps are valid
        sliced = False
        if start_col and end_col and pd.notna(row.get(start_col)) and pd.notna(row.get(end_col)):
            try:
                s_val = row[start_col]
                e_val = row[end_col]
                s_dt = s_val if isinstance(s_val, pd.Timestamp) else pd.to_datetime(s_val)
                e_dt = e_val if isinstance(e_val, pd.Timestamp) else pd.to_datetime(e_val)

                total_span = (e_dt - s_dt).total_seconds()
                if total_span > 0:
                    curr = s_dt
                    while curr < e_dt:
                        next_hr = curr.floor("h") + pd.Timedelta(hours=1)
                        hr_end = min(e_dt, next_hr)
                        hr_span = (hr_end - curr).total_seconds()
                        hr_active = active_sec * (hr_span / total_span)
                        c_idx = curr.hour
                        if 0 <= c_idx < 24:
                            matrix[r_idx, c_idx] += hr_active / 60.0
                        curr = hr_end
                    sliced = True
            except Exception:
                sliced = False

        if not sliced:
            time_b = str(row.get("time_bucket", "")).strip()
            hour_str = time_b.split(":")[0] if ":" in time_b else "0"
            try:
                c_idx = int(hour_str)
                if 0 <= c_idx < 24:
                    matrix[r_idx, c_idx] += active_sec / 60.0
            except ValueError:
                pass

    return np.round(matrix, 1)


def calculate_app_baselines(sessions_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate personal statistical baselines using robust NumPy statistics.

    Uses NumPy median, mean, standard deviation, and 75th/95th percentiles.
    """
    if sessions_df is None or sessions_df.empty:
        return pd.DataFrame(columns=[
            "process_name", "mean_daily_min", "median_daily_min", "std_daily_min",
            "p75_daily_min", "p95_daily_min", "days_observed"
        ])

    # First aggregate active duration per app per day
    daily_app = sessions_df.groupby(["process_name", "local_date"])["active_seconds"].sum().reset_index()
    daily_app["daily_minutes"] = daily_app["active_seconds"] / 60.0

    records = []
    for app_name, group in daily_app.groupby("process_name"):
        arr = group["daily_minutes"].to_numpy(dtype=np.float64)
        if len(arr) == 0:
            continue

        mean_val = float(np.mean(arr))
        median_val = float(np.median(arr))
        std_val = float(np.std(arr)) if len(arr) > 1 else 0.0
        p75_val = float(np.percentile(arr, 75))
        p95_val = float(np.percentile(arr, 95))

        records.append({
            "process_name": app_name,
            "mean_daily_min": round(mean_val, 1),
            "median_daily_min": round(median_val, 1),
            "std_daily_min": round(std_val, 1),
            "p75_daily_min": round(p75_val, 1),
            "p95_daily_min": round(p95_val, 1),
            "days_observed": int(len(arr)),
        })

    result_df = pd.DataFrame(records)
    if not result_df.empty:
        result_df = result_df.sort_values(by="median_daily_min", ascending=False).reset_index(drop=True)
    return result_df
