"""Phase 2 regression tests: duration formatting, table numeric sorting, and absence of decimal hours."""
from __future__ import annotations

import ast
import math
import os
import re
from pathlib import Path
import pytest
import pandas as pd
from PySide6.QtCore import Qt

from desktop_intelligence.formatting import (
    UNAVAILABLE,
    format_duration,
    format_duration_hours,
    format_tick_hours,
    nice_time_step_hours,
)
from desktop_intelligence.ui.pages.usage import DurationItem, NumericItem, UsagePage
from desktop_intelligence.visualization.charts import create_top_apps_chart


# 39 exhaustive duration formatter test cases covering all edge cases
FORMAT_CASES = [
    (None, False, UNAVAILABLE),
    (float("nan"), False, UNAVAILABLE),
    (float("inf"), False, UNAVAILABLE),
    (float("-inf"), False, UNAVAILABLE),
    ("invalid", False, UNAVAILABLE),
    (-10.0, False, "0 s"),
    (0.0, False, "0 s"),
    (0.4, False, "0 s"),
    (0.5, False, "1 s"),
    (1.0, False, "1 s"),
    (15.0, False, "15 s"),
    (36.0, False, "36 s"),
    (59.0, False, "59 s"),
    (59.4, False, "59 s"),
    (59.5, False, "1 min"),
    (60.0, False, "1 min"),
    (61.0, False, "1 min"),
    (90.0, False, "2 min"),
    (119.0, False, "2 min"),
    (359.0, False, "6 min"),
    (360.0, False, "6 min"),
    (1080.0, False, "18 min"),
    (2520.0, False, "42 min"),
    (3569.0, False, "59 min"),
    (3570.0, False, "1 h"),
    (3599.6, False, "1 h"),
    (3600.0, False, "1 h"),
    (3601.0, False, "1 h"),
    (3660.0, False, "1 h 01 min"),
    (3900.0, False, "1 h 05 min"),
    (7200.0, False, "2 h"),
    (7260.0, False, "2 h 01 min"),
    (10800.0, False, "3 h"),
    (14400.0, False, "4 h"),
    (172800.0, False, "48 h"),
    (172800.0, True, "2 d"),
    (187200.0, True, "2 d 4 h"),
    (259200.0, True, "3 d"),
    (360000.0, True, "4 d 4 h"),
]


@pytest.mark.parametrize("seconds,use_days,expected", FORMAT_CASES)
def test_format_duration_cases(seconds, use_days, expected):
    """Verify all 39 duration formatting test cases produce exact human-readable strings."""
    assert format_duration(seconds, use_days=use_days) == expected


def test_format_duration_hours():
    """Verify decimal hours helper converts cleanly to minutes and hours."""
    assert format_duration_hours(None) == UNAVAILABLE
    assert format_duration_hours("bad") == UNAVAILABLE
    assert format_duration_hours(0.0) == "0 s"
    assert format_duration_hours(0.7) == "42 min"
    assert format_duration_hours(1.0) == "1 h"
    assert format_duration_hours(1.5) == "1 h 30 min"
    assert format_duration_hours(2.0) == "2 h"


def test_chart_tick_formatter_and_steps():
    """Verify Matplotlib axis tick formatter handles zero, off-range and normal hours."""
    assert format_tick_hours(0.0) == "0"
    assert format_tick_hours(-0.5) == ""
    assert format_tick_hours(1.0) == "1 h"
    assert format_tick_hours(0.5) == "30 min"

    # Nice steps
    assert nice_time_step_hours(0.08) <= 0.08  # ~5 min span -> step 1 or 5 min
    assert nice_time_step_hours(1.0) in (10 / 60.0, 15 / 60.0, 30 / 60.0)
    assert nice_time_step_hours(8.0) in (1.0, 2.0, 3.0)


def test_chart_rendering_with_small_and_large_durations():
    """Verify top apps chart handles small durations (42 min, 18 min, 6 min, 36 s, 1 s) cleanly."""
    summary_df = pd.DataFrame([
        {"process_name": "app_42m.exe", "active_hours": 0.7, "active_seconds": 2520.0},
        {"process_name": "app_18m.exe", "active_hours": 0.3, "active_seconds": 1080.0},
        {"process_name": "app_6m.exe", "active_hours": 0.1, "active_seconds": 360.0},
        {"process_name": "app_36s.exe", "active_hours": 0.01, "active_seconds": 36.0},
        {"process_name": "app_1s.exe", "active_hours": 0.0003, "active_seconds": 1.0},
    ])
    fig = create_top_apps_chart(summary_df, top_n=5)
    ax = fig.axes[0]
    # Check bar labels contain human durations (e.g. 42 min, 18 min, 6 min, 36 s, 1 s)
    texts = [c.get_text() for c in ax.texts]
    assert any("42 min" in t for t in texts)
    assert any("18 min" in t for t in texts)
    assert any("6 min" in t for t in texts)
    assert any("36 s" in t for t in texts)
    assert any("1 s" in t for t in texts)


def test_usage_table_duration_item_sorting(qapp):
    """Verify DurationItem sorts numerically: 30 s < 45 min < 2 h, unlike alphabetical sorting."""
    item_30s = DurationItem(30.0)
    item_45m = DurationItem(2700.0)
    item_2h = DurationItem(7200.0)

    # In alphabetical sort: "2 h" < "30 s" < "45 min"
    assert "2 h" < "30 s" < "45 min"

    # In DurationItem sort: item_30s < item_45m < item_2h
    assert item_30s < item_45m
    assert item_45m < item_2h
    assert not (item_2h < item_30s)

    # Tooltip check
    assert "30 s (0.01 h)" in item_30s.toolTip()
    assert "2700 s (0.75 h)" in item_45m.toolTip()
    assert "7200 s (2.00 h)" in item_2h.toolTip()


def test_usage_page_table_population_and_column_sorting(qapp):
    """Verify UsagePage table loads durations as DurationItems and sorts correctly."""
    page = UsagePage()
    sessions = pd.DataFrame([
        {
            "session_id": "s1",
            "process_name": "ShortApp.exe",
            "active_seconds": 30.0,
            "duration_seconds": 30.0,
            "idle_seconds": 0.0,
            "local_date": "2026-10-18",
            "day_of_week": "Sunday",
            "time_bucket": "10:00",
        },
        {
            "session_id": "s2",
            "process_name": "MediumApp.exe",
            "active_seconds": 2700.0,
            "duration_seconds": 2700.0,
            "idle_seconds": 0.0,
            "local_date": "2026-10-18",
            "day_of_week": "Sunday",
            "time_bucket": "10:00",
        },
        {
            "session_id": "s3",
            "process_name": "LongApp.exe",
            "active_seconds": 7200.0,
            "duration_seconds": 7200.0,
            "idle_seconds": 0.0,
            "local_date": "2026-10-18",
            "day_of_week": "Sunday",
            "time_bucket": "10:00",
        },
    ])

    page.update_data(sessions)
    assert page.table.rowCount() == 3

    # Check cell text
    # Default order by active_hours descending: LongApp, MediumApp, ShortApp
    assert page.table.item(0, 0).text() == "LongApp.exe"
    assert page.table.item(0, 1).text() == "2 h"

    assert page.table.item(1, 0).text() == "MediumApp.exe"
    assert page.table.item(1, 1).text() == "45 min"

    assert page.table.item(2, 0).text() == "ShortApp.exe"
    assert page.table.item(2, 1).text() == "30 s"

    # Sort ascending by column 1 (Active Time)
    page.table.sortItems(1, Qt.AscendingOrder)
    assert page.table.item(0, 0).text() == "ShortApp.exe"
    assert page.table.item(1, 0).text() == "MediumApp.exe"
    assert page.table.item(2, 0).text() == "LongApp.exe"

    # Sort descending by column 1 (Active Time)
    page.table.sortItems(1, Qt.DescendingOrder)
    assert page.table.item(0, 0).text() == "LongApp.exe"
    assert page.table.item(1, 0).text() == "MediumApp.exe"
    assert page.table.item(2, 0).text() == "ShortApp.exe"


def test_no_decimal_hours_in_ui():
    """Verify that no UI pages display raw decimal hours like '0.7 hrs' or '{x:.1f} hrs'."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    ui_dir = repo_root / "desktop_intelligence" / "ui" / "pages"
    assert ui_dir.is_dir()

    forbidden_pattern = re.compile(r"""(\.([0-9]+)?f\s*hrs?)|(['"][0-9]+\.[0-9]+\s*hrs?['"])""", re.IGNORECASE)

    for py_file in ui_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        matches = forbidden_pattern.findall(content)
        assert not matches, f"Forbidden decimal hours pattern found in {py_file.name}: {matches}"
