"""Usage page showing detailed application breakdown table and trend charts."""

from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
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
from desktop_intelligence.visualization.charts import (
    ThemedChartCanvas,
    create_daily_trend_chart,
    create_day_of_week_chart,
    create_empty_figure,
)


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
        self.dow_canvas.setMinimumHeight(230)
        dow_box.addWidget(self.dow_canvas)
        charts_layout.addWidget(dow_card, stretch=1)

        layout.addLayout(charts_layout)

        # Table Section
        table_title = QLabel("Application Usage Breakdown")
        table_title.setObjectName("section_title")
        layout.addWidget(table_title)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Application", "Active Hours", "Idle Hours", "Total Hours",
            "Sessions", "% Active Time", "Avg Session (min)"
        ])
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, stretch=1)

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
        self.table.setRowCount(len(summary))
        for r_idx, row in summary.iterrows():
            self.table.setItem(r_idx, 0, QTableWidgetItem(str(row["process_name"])))
            self.table.setItem(r_idx, 1, QTableWidgetItem(f"{row['active_hours']:.2f} h"))
            self.table.setItem(r_idx, 2, QTableWidgetItem(f"{row['idle_hours']:.2f} h"))
            self.table.setItem(r_idx, 3, QTableWidgetItem(f"{row['total_hours']:.2f} h"))
            self.table.setItem(r_idx, 4, QTableWidgetItem(str(row["session_count"])))
            self.table.setItem(r_idx, 5, QTableWidgetItem(f"{row['pct_active_time']:.1f}%"))
            self.table.setItem(r_idx, 6, QTableWidgetItem(f"{row['avg_session_min']:.1f} m"))
