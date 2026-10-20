"""Automation page for reviewing approved launch rules, master toggle, and audit execution logs."""

from typing import Callable, List, Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop_intelligence.models import AutomationLogRecord, RecommendationRecord


class AutomationPage(QWidget):
    """Automation rules and execution log audit page."""

    def __init__(
        self,
        on_toggle_automation: Optional[Callable[[bool], None]] = None,
        on_mode_changed: Optional[Callable[[str], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.on_toggle_automation = on_toggle_automation
        self.on_mode_changed = on_mode_changed

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Title & Master Toggle Card
        header_card = QFrame()
        header_card.setObjectName("glass_card")
        header_box = QVBoxLayout(header_card)
        header_box.setContentsMargins(16, 14, 16, 14)
        header_box.setSpacing(10)

        top_bar = QHBoxLayout()
        title = QLabel("Workflow Automation")
        title.setObjectName("page_title")
        top_bar.addWidget(title)
        top_bar.addStretch()

        self.master_checkbox = QCheckBox("Enable Scheduled Automation")
        self.master_checkbox.setStyleSheet("font-size: 13px; font-weight: 600;")
        self.master_checkbox.toggled.connect(self._on_toggle)
        top_bar.addWidget(self.master_checkbox)
        header_box.addLayout(top_bar)

        # Mode Selector Bar
        mode_bar = QHBoxLayout()
        mode_label = QLabel("Automation Mode:")
        mode_label.setStyleSheet("font-size: 12px; font-weight: 600;")
        mode_bar.addWidget(mode_label)

        self.combo_mode = QComboBox()
        self.combo_mode.addItem("Disabled (Off)", "off")
        self.combo_mode.addItem("Prompt (Interactive Confirmation)", "prompt")
        self.combo_mode.addItem("Autonomous (Silent Launch)", "auto")
        self.combo_mode.addItem("Notify (Launch with Alert)", "notify")
        self.combo_mode.currentIndexChanged.connect(self._on_mode_selected)
        mode_bar.addWidget(self.combo_mode)
        mode_bar.addStretch()
        header_box.addLayout(mode_bar)

        # Consent banner
        self.banner = QLabel(
            "Consent Policy: Automation requires explicit user rule approval. Actions are predefined, auditable, and permission-gated."
        )
        self.banner.setObjectName("subtitle")
        self.banner.setStyleSheet(
            "border: 1px solid rgba(34, 211, 238, 0.25); background-color: rgba(34, 211, 238, 0.08); "
            "border-radius: 6px; padding: 10px; font-size: 11px;"
        )
        self.banner.setWordWrap(True)
        header_box.addWidget(self.banner)
        layout.addWidget(header_card)

        # Approved Rules Table
        rules_title = QLabel("Approved Scheduled Launch Rules")
        rules_title.setObjectName("section_title")
        layout.addWidget(rules_title)

        self.rules_table = QTableWidget()
        self.rules_table.setColumnCount(4)
        self.rules_table.setHorizontalHeaderLabels([
            "Rule ID", "Application & Context", "Confidence", "Status"
        ])
        self.rules_table.verticalHeader().setVisible(False)
        rules_header = self.rules_table.horizontalHeader()
        rules_header.setSectionResizeMode(QHeaderView.ResizeToContents)
        rules_header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.rules_table.setAlternatingRowColors(True)
        layout.addWidget(self.rules_table, stretch=1)

        # Audit Log Table
        log_title = QLabel("Automation Audit Log")
        log_title.setObjectName("section_title")
        layout.addWidget(log_title)

        self.log_table = QTableWidget()
        self.log_table.setColumnCount(5)
        self.log_table.setHorizontalHeaderLabels([
            "Timestamp (UTC)", "Rule ID", "Action", "Result", "Reason"
        ])
        self.log_table.verticalHeader().setVisible(False)
        log_header = self.log_table.horizontalHeader()
        log_header.setSectionResizeMode(QHeaderView.ResizeToContents)
        log_header.setSectionResizeMode(4, QHeaderView.Stretch)
        self.log_table.setAlternatingRowColors(True)
        layout.addWidget(self.log_table, stretch=1)

    def _on_toggle(self, checked: bool) -> None:
        target_mode = "prompt" if checked else "off"
        self.combo_mode.blockSignals(True)
        idx = self.combo_mode.findData(target_mode)
        if idx >= 0:
            self.combo_mode.setCurrentIndex(idx)
        self.combo_mode.blockSignals(False)

        if self.on_mode_changed:
            self.on_mode_changed(target_mode)
        elif self.on_toggle_automation:
            self.on_toggle_automation(checked)

    def _on_mode_selected(self, index: int) -> None:
        mode = self.combo_mode.itemData(index)
        if not mode:
            return
        is_enabled = (mode != "off")
        self.master_checkbox.blockSignals(True)
        self.master_checkbox.setChecked(is_enabled)
        self.master_checkbox.blockSignals(False)

        if self.on_mode_changed:
            self.on_mode_changed(mode)
        elif self.on_toggle_automation:
            self.on_toggle_automation(is_enabled)

    def update_data(
        self,
        automation_enabled: bool,
        rules: List[RecommendationRecord],
        logs: List[AutomationLogRecord],
        mode: str = "off",
    ) -> None:
        """Update automation state, rules table, and execution log table."""
        self.master_checkbox.blockSignals(True)
        self.master_checkbox.setChecked(automation_enabled)
        self.master_checkbox.blockSignals(False)

        self.combo_mode.blockSignals(True)
        idx = self.combo_mode.findData(mode)
        if idx >= 0:
            self.combo_mode.setCurrentIndex(idx)
        else:
            fallback = "prompt" if automation_enabled else "off"
            f_idx = self.combo_mode.findData(fallback)
            self.combo_mode.setCurrentIndex(f_idx if f_idx >= 0 else 0)
        self.combo_mode.blockSignals(False)

        # Approved rules
        approved_rules = [r for r in rules if r.status == "approved"]
        self.rules_table.setRowCount(len(approved_rules))
        for r_idx, r in enumerate(approved_rules):
            self.rules_table.setItem(r_idx, 0, QTableWidgetItem(r.recommendation_id))
            self.rules_table.setItem(r_idx, 1, QTableWidgetItem(r.subject))
            self.rules_table.setItem(r_idx, 2, QTableWidgetItem(f"{int(r.confidence * 100)}%"))
            item_status = QTableWidgetItem("Active" if automation_enabled else "Inactive (Automation Disabled)")
            item_status.setForeground(QColor("#34D399") if automation_enabled else QColor("#A7B2C8"))
            self.rules_table.setItem(r_idx, 3, item_status)

        # Logs
        self.log_table.setRowCount(len(logs))
        for r_idx, log in enumerate(reversed(logs)):
            self.log_table.setItem(r_idx, 0, QTableWidgetItem(log.ts_utc))
            self.log_table.setItem(r_idx, 1, QTableWidgetItem(log.rule_id))
            self.log_table.setItem(r_idx, 2, QTableWidgetItem(log.action))
            res_item = QTableWidgetItem(log.result)
            if log.result == "success":
                res_item.setForeground(QColor("#34D399"))
            elif "skip" in log.result:
                res_item.setForeground(QColor("#FBBF24"))
            else:
                res_item.setForeground(QColor("#FB7185"))
            self.log_table.setItem(r_idx, 3, res_item)
            self.log_table.setItem(r_idx, 4, QTableWidgetItem(log.reason))
