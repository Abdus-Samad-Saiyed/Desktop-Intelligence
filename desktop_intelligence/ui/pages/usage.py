"""Usage page showing detailed application breakdown table and trend charts."""

from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
import pandas as pd

from desktop_intelligence.analytics.usage import (
    calculate_usage_summary,
    calculate_daily_summary,
    calculate_day_of_week_distribution,
)
from desktop_intelligence.formatting import UNAVAILABLE, format_duration
from desktop_intelligence.visualization.charts import (
    ThemedChartCanvas,
    create_daily_trend_chart,
    create_day_of_week_chart,
    create_empty_figure,
)


class NumericItem(QTableWidgetItem):
    """Table item displaying formatted text and sorting numerically by raw value."""

    def __init__(self, text: str, sort_val: float):
        super().__init__(text)
        self.setData(Qt.UserRole, float(sort_val))

    def __lt__(self, other: object) -> bool:
        if isinstance(other, QTableWidgetItem):
            v1 = self.data(Qt.UserRole)
            v2 = other.data(Qt.UserRole)
            if v1 is not None and v2 is not None:
                return float(v1) < float(v2)
        return super().__lt__(other)


class DurationItem(NumericItem):
    """Table item displaying human-formatted duration and sorting numerically by seconds."""

    def __init__(self, seconds: Optional[float]):
        if seconds is None:
            super().__init__(UNAVAILABLE, -1.0)
            return
        try:
            sec = float(seconds)
            if pd.isna(sec):
                super().__init__(UNAVAILABLE, -1.0)
                return
        except (TypeError, ValueError):
            super().__init__(UNAVAILABLE, -1.0)
            return

        display_text = format_duration(sec)
        super().__init__(display_text, sec)
        if sec >= 0:
            self.setToolTip(f"{int(round(sec))} s ({sec / 3600.0:.2f} h)")


class UsagePage(QWidget):
    """Detailed usage analytics page."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Application Usage Analytics")
        title.setObjectName("page_title")
        layout.addWidget(title)

        # Charts section: side-by-side in glass cards
        charts_layout = QHBoxLayout()
        charts_layout.setSpacing(14)

        # Daily Trend Card
        trend_card = QFrame()
        trend_card.setObjectName("glass_card")
        trend_box = QVBoxLayout(trend_card)
        trend_box.setContentsMargins(12, 12, 12, 12)
        trend_box.setSpacing(6)
        self.trend_canvas = ThemedChartCanvas(create_empty_figure())
        self.trend_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.trend_canvas.setMinimumHeight(230)
        trend_box.addWidget(self.trend_canvas)
        charts_layout.addWidget(trend_card, stretch=1)

        # Day of Week Card
        dow_card = QFrame()
        dow_card.setObjectName("glass_card")
        dow_box = QVBoxLayout(dow_card)
        dow_box.setContentsMargins(12, 12, 12, 12)
        dow_box.setSpacing(6)
        self.dow_canvas = ThemedChartCanvas(create_empty_figure())
        self.dow_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.dow_canvas.setMinimumHeight(230)
        dow_box.addWidget(self.dow_canvas)
        charts_layout.addWidget(dow_card, stretch=1)

        layout.addLayout(charts_layout, stretch=2)

        # Table Section
        table_title = QLabel("Application Usage Breakdown")
        table_title.setObjectName("section_title")
        layout.addWidget(table_title)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Application", "Active Time", "Idle Time", "Total Time",
            "Sessions", "% Active Time", "Avg Session"
        ])
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table, stretch=3)

    def update_data(
        self,
        sessions_df: pd.DataFrame,
        theme_mode: str = "light",
        accent_color: Optional[str] = None,
    ) -> None:
        """Populate usage table and update trend charts."""
        if sessions_df is None or sessions_df.empty:
            self.table.setRowCount(0)
            self.trend_canvas.update_figure(
                create_empty_figure("No usage history available.", theme_mode, accent_color)
            )
            self.dow_canvas.update_figure(
                create_empty_figure("No weekly history available.", theme_mode, accent_color)
            )
            return

        summary = calculate_usage_summary(sessions_df)
        daily = calculate_daily_summary(sessions_df)
        dow = calculate_day_of_week_distribution(sessions_df)

        # Update charts using robust geometry-synchronizing method
        trend_fig = create_daily_trend_chart(daily, theme_mode, accent_color)
        self.trend_canvas.update_figure(trend_fig)

        dow_fig = create_day_of_week_chart(dow, theme_mode, accent_color)
        self.dow_canvas.update_figure(dow_fig)

        # Update table
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(summary))
        for r_idx, row in summary.iterrows():
            self.table.setItem(r_idx, 0, QTableWidgetItem(str(row["process_name"])))
            active_sec = row["active_seconds"] if "active_seconds" in row else row["active_hours"] * 3600.0
            idle_sec = row["idle_seconds"] if "idle_seconds" in row else row["idle_hours"] * 3600.0
            total_sec = row["total_seconds"] if "total_seconds" in row else row["total_hours"] * 3600.0
            avg_sec = row["avg_session_sec"] if "avg_session_sec" in row else row["avg_session_min"] * 60.0

            self.table.setItem(r_idx, 1, DurationItem(active_sec))
            self.table.setItem(r_idx, 2, DurationItem(idle_sec))
            self.table.setItem(r_idx, 3, DurationItem(total_sec))
            self.table.setItem(r_idx, 4, NumericItem(str(int(row["session_count"])), float(row["session_count"])))
            self.table.setItem(r_idx, 5, NumericItem(f"{row['pct_active_time']:.1f}%", float(row["pct_active_time"])))
            self.table.setItem(r_idx, 6, DurationItem(avg_sec))
        self.table.setSortingEnabled(True)
