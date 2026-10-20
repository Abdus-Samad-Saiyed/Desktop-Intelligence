"""Stage 8 tests: UI correctness, single-flight DataLoaderWorker, OverviewPage signature caching,
High-DPI canvas synchronization, system tray integration, and theme contrast.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import unittest.mock as mock
import pytest
import pandas as pd

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QSize
from PySide6.QtGui import QCloseEvent, QResizeEvent
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from desktop_intelligence.config import AppConfig
from desktop_intelligence.models import (
    ActivitySession,
    RecommendationRecord,
    format_utc_iso,
)
from desktop_intelligence.paths import resolve_paths
from desktop_intelligence.storage.csv_store import CsvStore
from desktop_intelligence.ui.main_window import MainWindow
from desktop_intelligence.ui.pages.overview import OverviewPage
from desktop_intelligence.ui.pages.settings import SettingsPage
from desktop_intelligence.ui.theme import (
    ACCENT_PRESETS,
    get_contrast_text_color,
    get_theme_palette,
)
from desktop_intelligence.visualization.charts import ThemedChartCanvas, create_empty_figure


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def test_themed_chart_canvas_geometry_and_dpi_synchronization(qapp):
    """Verify ThemedChartCanvas handles dimension syncing and High-DPI without distortion."""
    fig = create_empty_figure()
    canvas = ThemedChartCanvas(fig)

    # Initial size synchronization
    canvas.resize(800, 400)
    canvas._sync_dimensions()

    assert canvas.figure is not None
    # Figure size in inches should reflect 800x400 at figure.dpi
    expected_w_inches = 800.0 / canvas.figure.dpi
    expected_h_inches = 400.0 / canvas.figure.dpi
    assert canvas.figure.get_figwidth() == pytest.approx(expected_w_inches, rel=1e-2)
    assert canvas.figure.get_figheight() == pytest.approx(expected_h_inches, rel=1e-2)

    # Resize event with real QResizeEvent
    resize_event = QResizeEvent(QSize(600, 300), QSize(800, 400))
    canvas.resizeEvent(resize_event)

    assert canvas.figure.get_figwidth() == pytest.approx(600.0 / canvas.figure.dpi, rel=1e-2)
    assert canvas.figure.get_figheight() == pytest.approx(300.0 / canvas.figure.dpi, rel=1e-2)


def test_overview_page_signature_caching_skips_redundant_renders(qapp):
    """Verify OverviewPage does not re-render charts or rebuild widgets when data is identical."""
    page = OverviewPage()

    sessions_df = pd.DataFrame([
        {
            "session_id": "s_1",
            "process_name": "code.exe",
            "pid": "100",
            "start_ts_utc": "2026-10-19T10:00:00.000Z",
            "end_ts_utc": "2026-10-19T11:00:00.000Z",
            "duration_seconds": 3600.0,
            "idle_seconds": 0.0,
            "active_seconds": 3600.0,
            "local_date": "2026-10-19",
            "day_of_week": "Monday",
            "time_bucket": "10:00",
        }
    ])

    recs = [
        RecommendationRecord(
            recommendation_id="rec_1",
            created_ts_utc="2026-10-19T10:00:00.000Z",
            category="habit_launch",
            subject="Launch code.exe",
            evidence_json='{"day_of_week": "Monday", "frequency_percent": 85}',
            confidence=0.85,
            status="pending",
        )
    ]

    with mock.patch.object(page.chart_canvas, "update_figure", wraps=page.chart_canvas.update_figure) as mock_chart_update:
        # First call: Initial render
        page.update_data(sessions_df, recs, freshness_text="Just now")
        assert mock_chart_update.call_count == 1
        assert page.card_active.value_label.text() == "1 h"
        assert page.card_top_app.value_label.text() == "code.exe"

        # Second call with identical data: must update freshness text but SKIP chart update
        page.update_data(sessions_df, recs, freshness_text="1 min ago")
        assert mock_chart_update.call_count == 1  # Unchanged!
        assert page.card_freshness.value_label.text() == "1 min ago"

        # Third call with new session: must re-render chart
        new_df = pd.DataFrame([
            {
                "session_id": "s_2",
                "process_name": "browser.exe",
                "pid": "200",
                "start_ts_utc": "2026-10-19T11:00:00.000Z",
                "end_ts_utc": "2026-10-19T12:00:00.000Z",
                "duration_seconds": 3600.0,
                "idle_seconds": 0.0,
                "active_seconds": 3600.0,
                "local_date": "2026-10-19",
                "day_of_week": "Monday",
                "time_bucket": "11:00",
            }
        ])
        page.update_data(new_df, recs, freshness_text="Just now")
        assert mock_chart_update.call_count == 2
        assert page.card_top_app.value_label.text() == "browser.exe"


def test_main_window_single_flight_worker(qapp, tmp_path):
    """Verify trigger_refresh enforces single-flight worker and coalesces pending requests."""
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    paths.ensure_directories()
    store = CsvStore(paths)
    config = AppConfig()

    window = MainWindow(config=config, paths=paths, store=store)

    # Call trigger_refresh
    window.trigger_refresh()
    active_worker_1 = window._active_worker
    assert active_worker_1 is not None

    # Immediate second call while worker is running should set _refresh_pending and NOT replace worker
    if active_worker_1.isRunning():
        window.trigger_refresh()
        assert window._active_worker is active_worker_1
        assert window._refresh_pending is True

    # Wait for worker completion
    active_worker_1.wait(2000)
    window.close()


def test_main_window_system_tray_and_close_behavior(qapp, tmp_path, monkeypatch):
    """Verify system tray initialization, context menu, and closeEvent hide-to-tray."""
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    paths.ensure_directories()
    store = CsvStore(paths)
    config = AppConfig()
    config.ui.show_tray_icon = True

    # Mock isSystemTrayAvailable to return True in headless environment
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)

    window = MainWindow(config=config, paths=paths, store=store)
    window.show()

    # System tray should be configured
    assert window.tray_icon is not None
    menu = window.tray_icon.contextMenu()
    assert menu is not None
    actions = [a.text() for a in menu.actions()]
    assert "Open Dashboard" in actions
    assert "Refresh Data" in actions
    assert "Exit" in actions

    # Closing window when tray is active should ignore event and hide window
    close_event = QCloseEvent()
    window.closeEvent(close_event)
    assert close_event.isAccepted() is False
    assert window.isVisible() is False

    # Explicit quit should accept event and close cleanly
    window._is_quitting = True
    close_event2 = QCloseEvent()
    window.closeEvent(close_event2)
    assert close_event2.isAccepted() is True


def test_accent_presets_and_contrast_wcag_compliance(qapp, tmp_path):
    """Verify accent presets align with golden defaults and guarantee readable contrast."""
    # 1. Golden default #635BFF must be in ACCENT_PRESETS
    assert any(code.upper() == "#635BFF" for code in ACCENT_PRESETS.values())

    # 2. Contrast function gives light text on dark backgrounds and dark text on bright backgrounds
    assert get_contrast_text_color("#0A0D16") == "#FFFFFF"
    assert get_contrast_text_color("#635BFF") == "#FFFFFF"
    assert get_contrast_text_color("#FBBF24") == "#0F172A"  # Amber glow has bright luminance
    assert get_contrast_text_color("#22D3EE") == "#0F172A"  # Cyan glow has bright luminance

    # 3. Settings page populates all presets
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    config = AppConfig()
    page = SettingsPage(config=config, paths=paths)

    combo_items = [page.combo_accent.itemData(i).upper() for i in range(page.combo_accent.count())]
    for preset_hex in ACCENT_PRESETS.values():
        assert preset_hex.upper() in combo_items
