"""Regression tests for Stage 3: Chart edge cases, singular transformation prevention, and theming."""

import warnings
import numpy as np
import pandas as pd
import pytest

from desktop_intelligence.visualization.charts import (
    create_empty_figure,
    create_top_apps_chart,
    create_daily_trend_chart,
    create_day_of_week_chart,
    create_hourly_heatmap_chart,
    get_chart_theme_colors,
)


def test_chart_theme_colors():
    light_colors = get_chart_theme_colors("light", "#635BFF")
    assert light_colors["fig_bg"] == "#FFFFFF"
    assert light_colors["accent"] == "#635BFF"

    dark_colors = get_chart_theme_colors("dark", "#10B981")
    assert dark_colors["fig_bg"] == "#0E1422"
    assert dark_colors["accent"] == "#10B981"


def test_top_apps_chart_zero_hours_no_singular_warning():
    """Verify that all-zero hours do not produce identical xlims or singular warnings."""
    zero_df = pd.DataFrame({
        "process_name": ["code.exe", "slack.exe", "chrome.exe"],
        "active_hours": [0.0, 0.0, 0.0],
        "total_hours": [0.0, 0.0, 0.0],
    })

    with warnings.catch_warnings(record=True) as recorded_warnings:
        warnings.simplefilter("always")
        fig = create_top_apps_chart(zero_df, theme_mode="dark", accent_color="#8B83FF")

    singular_warnings = [w for w in recorded_warnings if "singular" in str(w.message).lower()]
    assert len(singular_warnings) == 0, f"Unexpected singular warning: {singular_warnings}"

    ax = fig.axes[0]
    xlim = ax.get_xlim()
    assert xlim[0] == 0.0
    assert xlim[1] >= 1.0
    assert xlim[1] > xlim[0]


def test_top_apps_chart_nan_and_empty():
    """Verify handling of empty or NaN values."""
    empty_df = pd.DataFrame()
    fig_empty = create_top_apps_chart(empty_df)
    assert len(fig_empty.axes) == 1

    none_fig = create_top_apps_chart(None)
    assert len(none_fig.axes) == 1

    nan_df = pd.DataFrame({
        "process_name": ["app1.exe", "app2.exe"],
        "active_hours": [np.nan, None],
    })
    with warnings.catch_warnings(record=True) as recorded_warnings:
        warnings.simplefilter("always")
        fig_nan = create_top_apps_chart(nan_df)
    singular_warnings = [w for w in recorded_warnings if "singular" in str(w.message).lower()]
    assert len(singular_warnings) == 0


def test_daily_trend_chart_zero_values_no_warning():
    """Verify daily trend chart with zero or empty hours."""
    daily_zero = pd.DataFrame({
        "local_date": ["2026-10-17", "2026-10-18"],
        "active_hours": [0.0, 0.0],
        "idle_hours": [0.0, 0.0],
    })
    with warnings.catch_warnings(record=True) as recorded_warnings:
        warnings.simplefilter("always")
        fig = create_daily_trend_chart(daily_zero, theme_mode="dark")
    singular_warnings = [w for w in recorded_warnings if "singular" in str(w.message).lower()]
    assert len(singular_warnings) == 0

    ax = fig.axes[0]
    ylim = ax.get_ylim()
    assert ylim[0] == 0.0
    assert ylim[1] >= 1.0


def test_day_of_week_chart_zero_and_theming():
    dow_zero = pd.DataFrame({
        "day_of_week": ["Monday", "Tuesday", "Wednesday"],
        "active_hours": [0.0, 0.0, 0.0],
    })
    with warnings.catch_warnings(record=True) as recorded_warnings:
        warnings.simplefilter("always")
        fig = create_day_of_week_chart(dow_zero, theme_mode="light", accent_color="#2563EB")
    singular_warnings = [w for w in recorded_warnings if "singular" in str(w.message).lower()]
    assert len(singular_warnings) == 0

    ax = fig.axes[0]
    assert ax.get_ylim()[1] >= 1.0


def test_hourly_heatmap_robustness():
    # All zeros matrix
    zeros_mat = np.zeros((7, 24))
    fig_zeros = create_hourly_heatmap_chart(zeros_mat)
    assert len(fig_zeros.axes) == 1  # Empty figure fallback

    # Valid matrix with some NaNs and Infs
    mat = np.ones((7, 24)) * 5.0
    mat[0, 0] = np.nan
    mat[1, 1] = np.inf
    fig_valid = create_hourly_heatmap_chart(mat, theme_mode="dark", accent_color="#8B83FF")
    assert len(fig_valid.axes) == 2  # Plot axis + Colorbar


def test_themed_chart_canvas_geometry_synchronization():
    """Verify ThemedChartCanvas binds canvas and synchronizes geometry to eliminate white rectangles."""
    import os
    import sys
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    from desktop_intelligence.visualization.charts import ThemedChartCanvas

    canvas = ThemedChartCanvas()
    canvas.resize(700, 350)

    # Initial figure has canvas bound
    assert canvas.figure.canvas is canvas

    # Update with new figure
    new_fig = create_top_apps_chart(
        pd.DataFrame({"process_name": ["app.exe"], "active_hours": [2.5]}),
        theme_mode="dark",
    )
    canvas.update_chart_figure(new_fig)

    assert canvas.figure is new_fig
    assert new_fig.canvas is canvas
    # Verify figure size in inches multiplied by dpi equals widget geometry
    px_size = new_fig.get_size_inches() * new_fig.dpi
    assert abs(px_size[0] - 700) < 2
    assert abs(px_size[1] - 350) < 2


def test_system_theme_resolution_matches_effective_mode(monkeypatch):
    """Verify that get_chart_theme_colors('system') canonicalizes to dark or light matching OS preference."""
    import desktop_intelligence.ui.theme as theme_mod

    # Case 1: Windows system reports dark mode
    monkeypatch.setattr(theme_mod, "is_system_dark_mode", lambda: True)
    dark_resolved = get_chart_theme_colors("system", "#8B5CF6")
    assert dark_resolved["fig_bg"] == "#0E1422"
    assert dark_resolved["text"] == "#F3F5FC"

    # Case 2: Windows system reports light mode
    monkeypatch.setattr(theme_mod, "is_system_dark_mode", lambda: False)
    light_resolved = get_chart_theme_colors("system", "#6957E8")
    assert light_resolved["fig_bg"] == "#FFFFFF"
    assert light_resolved["text"] == "#182033"


def test_themed_chart_canvas_multiple_resolutions():
    """Verify ThemedChartCanvas scales cleanly across standard window resolutions (1600x900, 1366x768, 1280x720)."""
    import os
    import sys
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QResizeEvent
    app = QApplication.instance() or QApplication(sys.argv)

    from desktop_intelligence.visualization.charts import ThemedChartCanvas

    canvas = ThemedChartCanvas()
    resolutions = [(800, 320), (680, 280), (600, 250)]

    for w, h in resolutions:
        canvas.resize(w, h)
        # Simulate Qt resizeEvent
        canvas.resizeEvent(QResizeEvent(QSize(w, h), QSize(100, 100)))
        fig_px = canvas.figure.get_size_inches() * canvas.figure.dpi
        assert abs(fig_px[0] - w) < 2
        assert abs(fig_px[1] - h) < 2


