"""Overview page showing key summary metrics, primary usage chart, and recommendations."""

import json
from typing import Callable, List, Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyleOption,
    QVBoxLayout,
    QWidget,
)

from desktop_intelligence.analytics.usage import calculate_usage_summary
from desktop_intelligence.formatting import UNAVAILABLE, format_duration
from desktop_intelligence.models import RecommendationRecord
from desktop_intelligence.visualization.charts import ThemedChartCanvas, create_top_apps_chart, create_empty_figure
import pandas as pd


class MetricCard(QFrame):
    """Clean metric summary card with design token styling."""

    def __init__(self, title: str, initial_value: str = UNAVAILABLE, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("glass_card")
        self.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        self.title_label = QLabel(title.upper())
        self.title_label.setObjectName("title")
        self.value_label = QLabel(initial_value)
        self.value_label.setObjectName("value")

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def paintEvent(self, event) -> None:
        opt = QStyleOption()
        opt.initFrom(self)
        p = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, p, self)
        super().paintEvent(event)

    def set_value(self, val: str) -> None:
        self.value_label.setText(val)


class RecommendationWidget(QFrame):
    """Widget displaying a single recommendation with action buttons."""

    def __init__(
        self,
        record: RecommendationRecord,
        on_action: Optional[Callable[[str, str], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.record = record
        self.on_action = on_action

        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("glass_card")
        self.setFrameShape(QFrame.StyledPanel)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(14)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        cat_badge = QLabel(f" {record.category.replace('_', ' ').title()} ")
        cat_badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        cat_badge.setStyleSheet(
            "background-color: rgba(139, 92, 246, 0.16); color: #8B5CF6; "
            "border-radius: 4px; font-weight: 600; font-size: 11px; padding: 2px 6px;"
        )
        conf_badge = QLabel(f"Confidence: {int(record.confidence * 100)}%")
        conf_badge.setObjectName("caption")
        conf_badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        header_layout.addWidget(cat_badge)
        header_layout.addWidget(conf_badge)
        header_layout.addStretch()

        subj_label = QLabel(record.subject)
        subj_label.setStyleSheet("font-size: 13px; font-weight: 600;")

        # Formatted evidence explanation
        try:
            ev = json.loads(record.evidence_json)
            if record.category == "habit_launch":
                expl = f"Launched {ev.get('launches_in_context', 0)} of {ev.get('context_occurrences', 0)} {ev.get('day_of_week')}s ({ev.get('frequency_percent', 0)}%)"
            elif record.category == "resource_hog":
                expl = f"Peak RAM: {ev.get('max_memory_percent')}% across {ev.get('sustained_samples')} samples. {ev.get('reason')}"
            else:
                expl = f"Installed application with zero launches observed over {ev.get('observation_days', 0)} days."
        except Exception:
            expl = record.evidence_json

        expl_label = QLabel(expl)
        expl_label.setObjectName("subtitle")
        expl_label.setWordWrap(True)

        text_layout.addLayout(header_layout)
        text_layout.addWidget(subj_label)
        text_layout.addWidget(expl_label)

        layout.addLayout(text_layout, stretch=1)

        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(6)
        btn_layout.setAlignment(Qt.AlignVCenter)
        approve_btn = QPushButton("Approve")
        approve_btn.setObjectName("primary_btn")
        approve_btn.setFixedWidth(80)

        reject_btn = QPushButton("Dismiss")
        reject_btn.setObjectName("danger_btn")
        reject_btn.setFixedWidth(80)

        approve_btn.clicked.connect(lambda: self._handle_click("approved"))
        reject_btn.clicked.connect(lambda: self._handle_click("rejected"))

        btn_layout.addWidget(approve_btn)
        btn_layout.addWidget(reject_btn)
        layout.addLayout(btn_layout)

    def paintEvent(self, event) -> None:
        opt = QStyleOption()
        opt.initFrom(self)
        p = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, p, self)
        super().paintEvent(event)

    def _handle_click(self, action: str) -> None:
        if self.on_action:
            self.on_action(self.record.recommendation_id, action)


class OverviewPage(QWidget):
    """Main overview dashboard page."""

    def __init__(
        self,
        on_rec_action: Optional[Callable[[str, str], None]] = None,
        on_navigate_health: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.on_rec_action = on_rec_action
        self.on_navigate_health = on_navigate_health

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # Title and status bar
        top_bar = QHBoxLayout()
        title = QLabel("System Overview")
        title.setObjectName("page_title")
        self.status_label = QLabel("Collection Status: Initializing")
        self.status_label.setStyleSheet("color: #64748B; font-weight: 600; font-size: 12px;")

        self.why_btn = QPushButton("Why?")
        self.why_btn.setObjectName("link_btn")
        self.why_btn.setCursor(Qt.PointingHandCursor)
        self.why_btn.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 2px 8px; border-radius: 4px; "
            "border: 1px solid #FBBF24; color: #FBBF24; background: rgba(251, 191, 36, 0.1); font-weight: 600; }"
            "QPushButton:hover { background: rgba(251, 191, 36, 0.2); }"
        )
        self.why_btn.hide()
        self.why_btn.clicked.connect(self._on_why_clicked)

        top_bar.addWidget(title)
        top_bar.addStretch()
        top_bar.addWidget(self.status_label)
        top_bar.addWidget(self.why_btn)
        main_layout.addLayout(top_bar)

        # 4 Metric Cards
        metrics_layout = QHBoxLayout()
        metrics_layout.setSpacing(14)
        self.card_active = MetricCard("TOTAL ACTIVE TIME", UNAVAILABLE)
        self.card_top_app = MetricCard("PRIMARY APPLICATION", UNAVAILABLE)
        self.card_sessions = MetricCard("TOTAL SESSIONS", "0")
        self.card_freshness = MetricCard("DATA FRESHNESS", "Up to date")

        metrics_layout.addWidget(self.card_active)
        metrics_layout.addWidget(self.card_top_app)
        metrics_layout.addWidget(self.card_sessions)
        metrics_layout.addWidget(self.card_freshness)
        main_layout.addLayout(metrics_layout)

        # Middle section: Chart Canvas in Glass Card Frame
        chart_card = QFrame()
        chart_card.setObjectName("glass_card")
        chart_card_layout = QVBoxLayout(chart_card)
        chart_card_layout.setContentsMargins(12, 12, 12, 12)
        chart_card_layout.setSpacing(6)

        self.chart_canvas = ThemedChartCanvas(create_empty_figure())
        self.chart_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.chart_canvas.setMinimumHeight(240)
        chart_card_layout.addWidget(self.chart_canvas)
        main_layout.addWidget(chart_card, stretch=3)

        # Bottom section: Recommendations
        rec_header = QLabel("Smart Recommendations & Habits")
        rec_header.setObjectName("section_title")
        main_layout.addWidget(rec_header)

        self.rec_scroll = QScrollArea()
        self.rec_scroll.setObjectName("rec_scroll")
        self.rec_scroll.setWidgetResizable(True)
        self.rec_scroll.setFrameShape(QFrame.NoFrame)
        self.rec_container = QWidget()
        self.rec_container.setObjectName("rec_container")
        self.rec_layout = QVBoxLayout(self.rec_container)
        self.rec_layout.setContentsMargins(0, 0, 0, 0)
        self.rec_layout.setSpacing(6)
        self.rec_scroll.setWidget(self.rec_container)
        main_layout.addWidget(self.rec_scroll, stretch=2)

        # Persistent empty-state message (never deleted across refreshes)
        self.empty_rec_label = QLabel("No pending recommendations. System is observing normal usage patterns.")
        self.empty_rec_label.setObjectName("subtitle")
        self.empty_rec_label.setStyleSheet("padding: 12px; font-style: italic;")
        self.rec_layout.addWidget(self.empty_rec_label)
        self.rec_layout.addStretch()

    def _clear_recommendations(self) -> None:
        """Safely remove dynamic recommendation widgets and spacer items without deleting persistent labels."""
        # Iterate backwards to safely remove widgets
        for i in reversed(range(self.rec_layout.count())):
            item = self.rec_layout.itemAt(i)
            if item is None:
                continue

            widget = item.widget()
            if widget is not None:
                if widget is not self.empty_rec_label:
                    self.rec_layout.removeWidget(widget)
                    widget.hide()
                    widget.setParent(None)
                    widget.deleteLater()
            else:
                # Remove spacer items
                self.rec_layout.removeItem(item)

    def _on_why_clicked(self) -> None:
        if self.on_navigate_health:
            self.on_navigate_health()

    def update_data(
        self,
        sessions_df: pd.DataFrame,
        recommendations: List[RecommendationRecord],
        freshness_text: str = "Up to date",
        collection_status_text: str = "Operational (Active)",
        theme_mode: str = "light",
        accent_color: Optional[str] = None,
    ) -> None:
        """Update metrics, chart, freshness card, and recommendations list."""
        self.status_label.setText(f"Collection Status: {collection_status_text}")
        if "Degraded" in collection_status_text:
            self.status_label.setStyleSheet("color: #FBBF24; font-weight: 600; font-size: 12px;")
            self.why_btn.setStyleSheet(
                "QPushButton { font-size: 11px; padding: 2px 8px; border-radius: 4px; "
                "border: 1px solid #FBBF24; color: #FBBF24; background: rgba(251, 191, 36, 0.1); font-weight: 600; }"
                "QPushButton:hover { background: rgba(251, 191, 36, 0.2); }"
            )
            self.why_btn.show()
        elif any(k in collection_status_text for k in ["Failed", "Warning", "Unavailable", "Error"]):
            self.status_label.setStyleSheet("color: #FB7185; font-weight: 600; font-size: 12px;")
            self.why_btn.setStyleSheet(
                "QPushButton { font-size: 11px; padding: 2px 8px; border-radius: 4px; "
                "border: 1px solid #FB7185; color: #FB7185; background: rgba(251, 113, 133, 0.1); font-weight: 600; }"
                "QPushButton:hover { background: rgba(251, 113, 133, 0.2); }"
            )
            self.why_btn.show()
        elif "Stopped" in collection_status_text:
            self.status_label.setStyleSheet("color: #94A3B8; font-weight: 600; font-size: 12px;")
            self.why_btn.hide()
        else:
            self.status_label.setStyleSheet("color: #34D399; font-weight: 600; font-size: 12px;")
            self.why_btn.hide()

        self.card_freshness.set_value(freshness_text)

        # Data signature check for flicker-free refreshes
        num_sessions = len(sessions_df) if sessions_df is not None else 0
        total_active_sec = float(sessions_df["active_seconds"].sum()) if (sessions_df is not None and not sessions_df.empty and "active_seconds" in sessions_df.columns) else 0.0
        last_session_id = str(sessions_df.iloc[-1].get("session_id", "")) if (sessions_df is not None and not sessions_df.empty and "session_id" in sessions_df.columns) else ""
        pending_ids = tuple(getattr(r, "recommendation_id", getattr(r, "rec_id", "")) for r in recommendations if getattr(r, "status", "") == "pending")
        data_sig = (num_sessions, round(total_active_sec, 1), last_session_id, pending_ids, theme_mode, accent_color)

        if data_sig == getattr(self, "_last_data_sig", None):
            return
        self._last_data_sig = data_sig

        if sessions_df is not None and not sessions_df.empty:
            summary_df = calculate_usage_summary(sessions_df)
            self.card_active.set_value(format_duration(total_active_sec, use_days=True))
            self.card_sessions.set_value(str(len(sessions_df)))

            if not summary_df.empty:
                top_name = summary_df.iloc[0]["process_name"]
                self.card_top_app.set_value(top_name)
                # Re-render chart using robust geometry-synchronizing method
                fig = create_top_apps_chart(
                    summary_df, top_n=6, theme_mode=theme_mode, accent_color=accent_color
                )
                self.chart_canvas.update_figure(fig)
            else:
                self.card_top_app.set_value(UNAVAILABLE)
        else:
            self.card_active.set_value(UNAVAILABLE)
            self.card_top_app.set_value(UNAVAILABLE)
            self.card_sessions.set_value("0")
            fig = create_empty_figure(
                "No application usage recorded.", theme_mode=theme_mode, accent_color=accent_color
            )
            self.chart_canvas.update_figure(fig)

        # Update recommendations safely
        self._clear_recommendations()

        pending_recs = [r for r in recommendations if r.status == "pending"]
        if not pending_recs:
            self.empty_rec_label.show()
            self.rec_layout.addStretch()
        else:
            self.empty_rec_label.hide()
            for rec in pending_recs:
                rw = RecommendationWidget(rec, on_action=self.on_rec_action)
                self.rec_layout.addWidget(rw)
            self.rec_layout.addStretch()
