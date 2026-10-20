"""Interactive launch consent prompt dialog with countdown timer."""

from typing import Optional
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop_intelligence.automation.rules import AutomationRule


class LaunchConsentDialog(QDialog):
    """Interactive modal consent dialog with a 10-second countdown."""

    def __init__(
        self,
        rule: AutomationRule,
        timeout_seconds: int = 10,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.rule = rule
        self.remaining_seconds = max(1, timeout_seconds)
        self.user_choice = "timeout"

        self.setWindowTitle("Automation Launch Request")
        self.setMinimumWidth(380)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        header = QLabel("Scheduled Application Launch")
        header.setStyleSheet("font-weight: bold; font-size: 15px;")
        layout.addWidget(header)

        msg = QLabel(
            f"Desktop Intelligence is requesting approval to launch:\n\n"
            f"<b>{rule.app_name}</b>\n"
            f"<span style='color: #64748B; font-size: 11px;'>Scheduled: {rule.day_of_week} at {rule.time_bucket}<br>Target: {rule.exe_path}</span>"
        )
        msg.setWordWrap(True)
        layout.addWidget(msg)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_skip = QPushButton(f"Skip ({self.remaining_seconds}s)")
        self.btn_skip.clicked.connect(self._on_skip)

        self.btn_launch = QPushButton("Launch Now")
        self.btn_launch.setStyleSheet("background-color: #635BFF; color: white; font-weight: 600; padding: 6px 14px; border-radius: 6px;")
        self.btn_launch.clicked.connect(self._on_launch)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_skip)
        btn_layout.addWidget(self.btn_launch)
        layout.addLayout(btn_layout)

        # Countdown timer
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._on_tick)
        self.timer.start()

    def _on_tick(self) -> None:
        self.remaining_seconds -= 1
        if self.remaining_seconds <= 0:
            self.timer.stop()
            self.user_choice = "timeout"
            self.accept()
        else:
            self.btn_skip.setText(f"Skip ({self.remaining_seconds}s)")

    def _on_skip(self) -> None:
        self.timer.stop()
        self.user_choice = "reject"
        self.reject()

    def _on_launch(self) -> None:
        self.timer.stop()
        self.user_choice = "approve"
        self.accept()


def show_launch_consent_dialog(
    rule: AutomationRule,
    timeout_seconds: int = 10,
    parent: Optional[QWidget] = None,
) -> str:
    """Show interactive consent dialog and return 'approve', 'reject', or 'timeout'."""
    dlg = LaunchConsentDialog(rule, timeout_seconds=timeout_seconds, parent=parent)
    dlg.exec()
    return dlg.user_choice
