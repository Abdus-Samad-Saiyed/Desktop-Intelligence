"""System Health page displaying memory consumption alerts and Windows reliability events."""

from typing import List, Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
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

from desktop_intelligence.analytics.resources import ResourceHogFinding, analyze_resource_hogs
from desktop_intelligence.collectors.resource_snapshot import format_bytes_to_human
from desktop_intelligence.collectors.system_errors import SystemErrorEvent
from desktop_intelligence.config import ResourcesConfig


class HealthPage(QWidget):
    """System Health and Error Monitoring page."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("System Health & Reliability")
        title.setObjectName("page_title")
        layout.addWidget(title)

        # Collector Health & Service Diagnostics Section
        col_header_layout = QHBoxLayout()
        col_title = QLabel("Background Event Collectors & Operating Mode")
        col_title.setObjectName("section_title")
        self.collector_summary_lbl = QLabel("Operational")
        self.collector_summary_lbl.setObjectName("caption")
        col_header_layout.addWidget(col_title)
        col_header_layout.addStretch()
        col_header_layout.addWidget(self.collector_summary_lbl)
        layout.addLayout(col_header_layout)

        self.collector_table = QTableWidget()
        self.collector_table.setColumnCount(6)
        self.collector_table.setHorizontalHeaderLabels([
            "Collector", "Status", "Mode", "Events", "Reason & Impact", "Remediation"
        ])
        self.collector_table.verticalHeader().setVisible(False)
        col_hdr = self.collector_table.horizontalHeader()
        col_hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        col_hdr.setSectionResizeMode(4, QHeaderView.Stretch)
        self.collector_table.setAlternatingRowColors(True)
        self.collector_table.setMaximumHeight(140)
        layout.addWidget(self.collector_table)

        # Resource Hog Section
        hog_title = QLabel("Memory Consumption & Resource Alerts")
        hog_title.setObjectName("section_title")
        layout.addWidget(hog_title)

        self.hog_table = QTableWidget()
        self.hog_table.setColumnCount(6)
        self.hog_table.setHorizontalHeaderLabels([
            "Process", "Peak RAM %", "Avg RAM %", "Peak RSS", "Observations", "Status"
        ])
        self.hog_table.verticalHeader().setVisible(False)
        hog_header = self.hog_table.horizontalHeader()
        hog_header.setSectionResizeMode(QHeaderView.ResizeToContents)
        hog_header.setSectionResizeMode(0, QHeaderView.Stretch)
        self.hog_table.setAlternatingRowColors(True)
        layout.addWidget(self.hog_table, stretch=1)

        # Application Error Logs Section
        err_header = QHBoxLayout()
        err_title = QLabel("Windows Application Reliability Events")
        err_title.setObjectName("section_title")
        self.diag_status = QLabel("Diagnostics: Checking...")
        self.diag_status.setObjectName("caption")
        err_header.addWidget(err_title)
        err_header.addStretch()
        err_header.addWidget(self.diag_status)
        layout.addLayout(err_header)

        self.error_table = QTableWidget()
        self.error_table.setColumnCount(6)
        self.error_table.setHorizontalHeaderLabels([
            "Application", "Type", "Error Code", "Faulting Module", "Timestamp (UTC)", "Description"
        ])
        self.error_table.verticalHeader().setVisible(False)
        err_tbl_header = self.error_table.horizontalHeader()
        err_tbl_header.setSectionResizeMode(QHeaderView.ResizeToContents)
        err_tbl_header.setSectionResizeMode(5, QHeaderView.Stretch)
        self.error_table.setAlternatingRowColors(True)
        layout.addWidget(self.error_table, stretch=1)

    def update_data(
        self,
        samples_df: pd.DataFrame,
        errors: List[SystemErrorEvent],
        diagnostic_status: str = "Operational",
        config: Optional[ResourcesConfig] = None,
        health_summary: Optional[object] = None,
    ) -> None:
        """Update resource consumption and error event tables."""
        self.diag_status.setText(f"Diagnostics: {diagnostic_status}")

        # Update collector health table
        if health_summary is not None and hasattr(health_summary, "collectors"):
            cols = health_summary.collectors
            self.collector_summary_lbl.setText(f"Status: {health_summary.overall_status}")
            self.collector_table.setRowCount(len(cols))
            for r_idx, c in enumerate(cols):
                self.collector_table.setItem(r_idx, 0, QTableWidgetItem(c.name))
                st_item = QTableWidgetItem(c.state.capitalize())
                if c.state == "active":
                    st_item.setForeground(QColor("#34D399"))
                elif c.state == "degraded":
                    st_item.setForeground(QColor("#FBBF24"))
                elif c.state in ("failed", "unavailable"):
                    st_item.setForeground(QColor("#FB7185"))
                else:
                    st_item.setForeground(QColor("#94A3B8"))
                self.collector_table.setItem(r_idx, 1, st_item)

                mode_text = (getattr(c, "mode", None) or "-").upper()
                self.collector_table.setItem(r_idx, 2, QTableWidgetItem(mode_text))
                self.collector_table.setItem(r_idx, 3, QTableWidgetItem(str(getattr(c, "event_count", 0))))

                reason = getattr(c, "reason", None)
                impact = getattr(c, "impact", None)
                msg = getattr(c, "message", "")
                reason_impact = f"{reason} | {impact}" if (reason and impact) else (reason or msg)
                self.collector_table.setItem(r_idx, 4, QTableWidgetItem(reason_impact or "-"))

                remediation = getattr(c, "remediation", None)
                remed_item = QTableWidgetItem(remediation or "None required")
                if remediation:
                    remed_item.setForeground(QColor("#FBBF24"))
                self.collector_table.setItem(r_idx, 5, remed_item)

        # Update resource hogs table
        findings = analyze_resource_hogs(samples_df, config)
        self.hog_table.setRowCount(len(findings))
        for r_idx, f in enumerate(findings):
            self.hog_table.setItem(r_idx, 0, QTableWidgetItem(f.process_name))
            self.hog_table.setItem(r_idx, 1, QTableWidgetItem(f"{f.max_memory_percent:.1f}%"))
            self.hog_table.setItem(r_idx, 2, QTableWidgetItem(f"{f.avg_memory_percent:.1f}%"))
            self.hog_table.setItem(r_idx, 3, QTableWidgetItem(format_bytes_to_human(f.max_rss_bytes)))
            self.hog_table.setItem(r_idx, 4, QTableWidgetItem(str(f.sustained_samples)))

            status_item = QTableWidgetItem("HIGH USAGE ALERT" if f.is_hog else "Normal")
            if f.is_hog:
                status_item.setForeground(QColor("#FB7185"))
            else:
                status_item.setForeground(QColor("#34D399"))
            self.hog_table.setItem(r_idx, 5, status_item)

        # Update error table
        self.error_table.setRowCount(len(errors))
        for r_idx, err in enumerate(errors):
            self.error_table.setItem(r_idx, 0, QTableWidgetItem(err.app_name))

            sev = getattr(err, "severity", "Report")
            sev_item = QTableWidgetItem(sev)
            if sev == "Crash":
                sev_item.setForeground(QColor("#FB7185"))
            elif sev == "Hang":
                sev_item.setForeground(QColor("#FBBF24"))
            else:
                sev_item.setForeground(QColor("#22D3EE"))
            self.error_table.setItem(r_idx, 1, sev_item)

            self.error_table.setItem(r_idx, 2, QTableWidgetItem(err.error_code or "-"))
            self.error_table.setItem(r_idx, 3, QTableWidgetItem(err.faulting_module or "-"))
            self.error_table.setItem(r_idx, 4, QTableWidgetItem(err.event_ts_utc))
            self.error_table.setItem(r_idx, 5, QTableWidgetItem(err.description))
