"""Stage 2 regression tests: Overview page recommendation widget lifecycle across repeated refreshes."""

import os
import sys
import pandas as pd
import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication

from desktop_intelligence.models import RecommendationRecord, format_utc_iso, now_utc
from desktop_intelligence.ui.pages.overview import OverviewPage, RecommendationWidget


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def make_rec(rec_id: str, subject: str, status: str = "pending") -> RecommendationRecord:
    return RecommendationRecord(
        recommendation_id=rec_id,
        created_ts_utc=format_utc_iso(now_utc()),
        category="habit_launch",
        subject=subject,
        evidence_json='{"app_name": "app.exe", "frequency_percent": 85.0}',
        confidence=0.85,
        status=status,
    )


def test_overview_page_repeated_refreshes_across_all_transitions(qapp):
    """Test the 8 transitions to prove no RuntimeError or deleted-object crashes occur."""
    page = OverviewPage()
    page.show()
    empty_df = pd.DataFrame()

    # Transition 1: Empty -> Empty
    page.update_data(empty_df, [])
    assert page.empty_rec_label.isVisible()

    page.update_data(empty_df, [])
    assert page.empty_rec_label.isVisible()

    # Transition 2: Empty -> Populated
    rec1 = make_rec("rec1", "Launch App 1")
    rec2 = make_rec("rec2", "Launch App 2")
    page.update_data(empty_df, [rec1, rec2])
    assert not page.empty_rec_label.isVisible()
    rec_widgets = [page.rec_layout.itemAt(i).widget() for i in range(page.rec_layout.count()) if isinstance(page.rec_layout.itemAt(i).widget(), RecommendationWidget)]
    assert len(rec_widgets) == 2

    # Transition 3: Populated -> Empty
    page.update_data(empty_df, [])
    assert page.empty_rec_label.isVisible()
    rec_widgets = [page.rec_layout.itemAt(i).widget() for i in range(page.rec_layout.count()) if isinstance(page.rec_layout.itemAt(i).widget(), RecommendationWidget)]
    assert len(rec_widgets) == 0

    # Transition 4: One recommendation -> Several recommendations
    rec3 = make_rec("rec3", "Launch App 3")
    page.update_data(empty_df, [rec3])
    assert not page.empty_rec_label.isVisible()
    rec_widgets = [page.rec_layout.itemAt(i).widget() for i in range(page.rec_layout.count()) if isinstance(page.rec_layout.itemAt(i).widget(), RecommendationWidget)]
    assert len(rec_widgets) == 1

    rec4 = make_rec("rec4", "Launch App 4")
    rec5 = make_rec("rec5", "Launch App 5")
    page.update_data(empty_df, [rec3, rec4, rec5])
    assert not page.empty_rec_label.isVisible()
    rec_widgets = [page.rec_layout.itemAt(i).widget() for i in range(page.rec_layout.count()) if isinstance(page.rec_layout.itemAt(i).widget(), RecommendationWidget)]
    assert len(rec_widgets) == 3

    # Transition 5: Several recommendations -> One recommendation
    page.update_data(empty_df, [rec5])
    assert not page.empty_rec_label.isVisible()
    rec_widgets = [page.rec_layout.itemAt(i).widget() for i in range(page.rec_layout.count()) if isinstance(page.rec_layout.itemAt(i).widget(), RecommendationWidget)]
    assert len(rec_widgets) == 1

    # Transition 6: Repeated refreshes with unchanged data
    for _ in range(5):
        page.update_data(empty_df, [rec5])
        assert not page.empty_rec_label.isVisible()
        rec_widgets = [page.rec_layout.itemAt(i).widget() for i in range(page.rec_layout.count()) if isinstance(page.rec_layout.itemAt(i).widget(), RecommendationWidget)]
        assert len(rec_widgets) == 1

    # Transition 7: Empty data arriving after populated data
    page.update_data(empty_df, [])
    assert page.empty_rec_label.isVisible()
    rec_widgets = [page.rec_layout.itemAt(i).widget() for i in range(page.rec_layout.count()) if isinstance(page.rec_layout.itemAt(i).widget(), RecommendationWidget)]
    assert len(rec_widgets) == 0

    # Transition 8: Recommendation approved/dismissed (status != 'pending')
    approved_rec = make_rec("rec5", "Launch App 5", status="approved")
    page.update_data(empty_df, [approved_rec])
    # Since approved_rec is not pending, empty label should be shown
    assert page.empty_rec_label.isVisible()
    rec_widgets = [page.rec_layout.itemAt(i).widget() for i in range(page.rec_layout.count()) if isinstance(page.rec_layout.itemAt(i).widget(), RecommendationWidget)]
    assert len(rec_widgets) == 0
