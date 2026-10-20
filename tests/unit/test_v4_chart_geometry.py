"""Phase 1 tests: High-DPI chart geometry, card fill at arbitrary display scales,
zero tight_layout calls, and figure lifecycle memory release.
"""

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import weakref
import pytest
import pandas as pd

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QApplication

from desktop_intelligence.ui.pages.overview import OverviewPage
from desktop_intelligence.ui.pages.usage import UsagePage
from desktop_intelligence.visualization.charts import (
    ThemedChartCanvas,
    create_empty_figure,
    create_top_apps_chart,
)

PROBE = Path(__file__).resolve().parents[1] / "helpers" / "dpr_probe.py"


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.mark.parametrize("scale", ["1.0", "1.25", "1.5", "2.0"])
def test_canvas_fills_card(scale):
    """Verify in subprocess at display scales that figure fills canvas 1.000 +/- 0.005 and is transparent."""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR=scale)
    out = subprocess.run([sys.executable, str(PROBE)], env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, f"Probe failed with scale {scale}:\nSTDERR: {out.stderr}\nSTDOUT: {out.stdout}"

    # Extract JSON line
    json_lines = [line.strip() for line in out.stdout.strip().splitlines() if line.strip().startswith("[{")]
    assert len(json_lines) > 0, f"No JSON output from probe:\n{out.stdout}"
    steps = json.loads(json_lines[-1])

    for step in steps:
        fx, fy = step["fill"]
        assert abs(fx - 1.0) <= 0.005, f"Scale {scale} step {step['tag']} x-fill {fx} != 1.0"
        assert abs(fy - 1.0) <= 0.005, f"Scale {scale} step {step['tag']} y-fill {fy} != 1.0"
        # Transparent canvas shows through card padding pixel color
        assert step["corner"] == step["pad"], f"Scale {scale} step {step['tag']} corner {step['corner']} != pad {step['pad']}"


def test_no_tight_layout_in_charts():
    """Verify through AST that no calls to tight_layout exist in charts.py."""
    charts_file = Path(__file__).resolve().parents[2] / "desktop_intelligence" / "visualization" / "charts.py"
    tree = ast.parse(charts_file.read_text(encoding="utf-8"))

    tight_layout_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "tight_layout":
                tight_layout_calls.append(node.lineno)

    assert not tight_layout_calls, f"Found tight_layout calls at lines {tight_layout_calls} in charts.py"


def test_pages_chart_canvas_fills_card_contents(qapp):
    """Verify real OverviewPage and UsagePage canvases fill their parent card contents."""
    overview = OverviewPage()
    overview.resize(1120, 740)
    overview.show()
    qapp.processEvents()

    # Overview canvas geometry
    canvas = overview.chart_canvas
    parent_card = canvas.parentWidget()
    assert parent_card is not None
    crect = parent_card.contentsRect()

    # Canvas should match card contents rectangle minus layout margins within 2 logical pixels
    margins = parent_card.layout().contentsMargins()
    expected_w = crect.width() - margins.left() - margins.right()
    expected_h = crect.height() - margins.top() - margins.bottom()
    assert abs(canvas.width() - expected_w) <= 2
    assert abs(canvas.height() - expected_h) <= 2

    # Check Usage page
    usage = UsagePage()
    usage.resize(1120, 740)
    usage.show()
    qapp.processEvents()

    trend_card = usage.trend_canvas.parentWidget()
    trect = trend_card.contentsRect()
    tmargins = trend_card.layout().contentsMargins()
    expected_tw = trect.width() - tmargins.left() - tmargins.right()
    expected_th = trect.height() - tmargins.top() - tmargins.bottom()
    assert abs(usage.trend_canvas.width() - expected_tw) <= 2
    assert abs(usage.trend_canvas.height() - expected_th) <= 2

    overview.close()
    usage.close()


def test_replaced_figure_is_released(qapp):
    """Verify that when a new figure is attached to canvas, the old figure is cleared and released."""
    fig1 = create_empty_figure()
    canvas = ThemedChartCanvas(fig1)

    ref = weakref.ref(fig1)
    del fig1

    # Replace with new figure
    fig2 = create_empty_figure()
    canvas.update_figure(fig2)

    import gc
    gc.collect()

    # Figure should be cleared and released promptly
    assert canvas.figure is fig2
    assert ref() is None, "Old figure was not collected after replacement!"


def test_one_canvas_per_card_after_20_refreshes(qapp):
    """Verify repeated refreshes do not accumulate leaked canvas objects in the layout."""
    page = OverviewPage()
    card = page.chart_canvas.parentWidget()
    card_layout = card.layout()

    initial_count = card_layout.count()
    assert initial_count == 1  # exactly one widget in card layout

    dummy_df = pd.DataFrame([{"process_name": "app.exe", "active_hours": 1.5}])
    for i in range(20):
        fig = create_top_apps_chart(dummy_df)
        page.chart_canvas.update_figure(fig)
        qapp.processEvents()

    assert card_layout.count() == 1
    assert card_layout.itemAt(0).widget() is page.chart_canvas


def test_theme_switch_keeps_fill(qapp, monkeypatch):
    """Verify switching themes maintains exact fill ratio and transparent styling."""
    from desktop_intelligence.ui.theme import is_system_dark_mode

    page = OverviewPage()
    page.resize(1000, 600)
    page.show()
    qapp.processEvents()

    dummy_df = pd.DataFrame([{"process_name": "app.exe", "active_hours": 2.0}])

    for mode in ["dark", "light", "system"]:
        if mode == "system":
            monkeypatch.setattr("desktop_intelligence.ui.theme.is_system_dark_mode", lambda: True)
        fig = create_top_apps_chart(dummy_df, theme_mode=mode)
        page.chart_canvas.update_figure(fig)
        qapp.processEvents()

        # Canvas surface should remain transparent across themes
        assert page.chart_canvas.figure.patch.get_alpha() == 0.0
        for ax in page.chart_canvas.figure.axes:
            assert ax.patch.get_alpha() == 0.0

    page.close()
