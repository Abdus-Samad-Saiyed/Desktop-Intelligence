"""Applications Inventory page showing installed software and observation history."""

from typing import List, Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop_intelligence.models import InventoryItem


class ApplicationsPage(QWidget):
    """Application inventory and observation history page."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.all_items: List[InventoryItem] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Title and Search
        header_layout = QHBoxLayout()
        title = QLabel("Application Inventory & Discovery")
        title.setObjectName("page_title")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search applications...")
        self.search_input.setFixedWidth(240)
        self.search_input.textChanged.connect(self._filter_table)
        header_layout.addWidget(self.search_input)
        layout.addLayout(header_layout)

        # Stats banner
        self.stats_banner = QLabel("Total Installed: 0 | Observed in Use: 0 | Not Observed: 0")
        self.stats_banner.setObjectName("subtitle")
        layout.addWidget(self.stats_banner)

        # Inventory Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            "Application Name", "Discovery Source", "Observed Launches", "Observation Status"
        ])
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, stretch=1)

    def update_data(self, items: List[InventoryItem]) -> None:
        """Update inventory items and refresh table."""
        self.all_items = sorted(items, key=lambda x: (x.observed_launch_count == 0, x.display_name.lower()))
        self._filter_table()

    def _filter_table(self) -> None:
        query = self.search_input.text().lower().strip()
        filtered = [
            item for item in self.all_items
            if query in item.display_name.lower() or query in item.exe_path.lower()
        ]

        total_count = len(self.all_items)
        observed_count = sum(1 for item in self.all_items if item.observed_launch_count > 0)
        unobserved_count = total_count - observed_count

        self.stats_banner.setText(
            f"Total Installed: {total_count} | Observed in Use: {observed_count} | "
            f"Not Observed Since Monitoring Began: {unobserved_count}"
        )

        self.table.setRowCount(len(filtered))
        for r_idx, item in enumerate(filtered):
            self.table.setItem(r_idx, 0, QTableWidgetItem(item.display_name))
            self.table.setItem(r_idx, 1, QTableWidgetItem(item.inventory_source))
            self.table.setItem(r_idx, 2, QTableWidgetItem(str(item.observed_launch_count)))

            if item.observed_launch_count > 0:
                status_text = f"Active (last seen: {item.last_observed_launch_ts_utc[:10] if item.last_observed_launch_ts_utc else 'observed'})"
                status_item = QTableWidgetItem(status_text)
                status_item.setForeground(QColor("#34D399"))
            else:
                first_date = item.first_seen_ts_utc[:10] if item.first_seen_ts_utc else "start"
                status_text = f"Not observed since monitoring began on {first_date}"
                status_item = QTableWidgetItem(status_text)
                status_item.setForeground(QColor("#A7B2C8"))

            self.table.setItem(r_idx, 3, status_item)
