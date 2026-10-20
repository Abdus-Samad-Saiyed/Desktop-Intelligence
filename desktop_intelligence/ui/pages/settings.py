"""Settings page allowing user configuration updates and diagnostic inspection."""

from pathlib import Path
from typing import Callable, Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from desktop_intelligence.config import AppConfig
from desktop_intelligence.paths import ResolvedPaths


class SettingsPage(QWidget):
    """Application settings and path diagnostics page."""

    def __init__(
        self,
        config: AppConfig,
        paths: ResolvedPaths,
        on_save_config: Optional[Callable[[AppConfig], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.config = config
        self.paths = paths
        self.on_save_config = on_save_config

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        title = QLabel("Configuration & Settings")
        title.setObjectName("page_title")
        layout.addWidget(title)

        # Preferences Card
        pref_card = QFrame()
        pref_card.setObjectName("glass_card")
        pref_box = QVBoxLayout(pref_card)
        pref_box.setContentsMargins(18, 16, 18, 16)
        pref_box.setSpacing(12)

        pref_title = QLabel("Application & Collection Preferences")
        pref_title.setObjectName("section_title")
        pref_box.addWidget(pref_title)

        form = QFormLayout()
        form.setSpacing(12)

        # Log Level
        self.combo_log_level = QComboBox()
        self.combo_log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.combo_log_level.setCurrentText(config.general.log_level)
        form.addRow("Logging Level:", self.combo_log_level)

        # Theme
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["light", "dark", "system"])
        self.combo_theme.setCurrentText(config.ui.theme)
        form.addRow("UI Theme:", self.combo_theme)

        # Accent Color
        self.combo_accent = QComboBox()
        from desktop_intelligence.ui.theme import ACCENT_PRESETS
        curr_accent = getattr(config.ui, "accent_color", "#635BFF").strip().upper()
        selected_idx = 0
        idx = 0
        for label, hex_val in ACCENT_PRESETS.items():
            self.combo_accent.addItem(f"{label} ({hex_val})", hex_val)
            if hex_val.upper() == curr_accent:
                selected_idx = idx
            idx += 1
        if curr_accent not in [v.upper() for v in ACCENT_PRESETS.values()]:
            self.combo_accent.addItem(f"Custom ({curr_accent})", curr_accent)
            selected_idx = self.combo_accent.count() - 1
        self.combo_accent.setCurrentIndex(selected_idx)
        form.addRow("Accent Color:", self.combo_accent)

        # Idle Timeout
        self.spin_idle = QSpinBox()
        self.spin_idle.setRange(30, 3600)
        self.spin_idle.setValue(config.collection.idle_timeout_seconds)
        self.spin_idle.setSuffix(" seconds")
        form.addRow("Idle Inactivity Timeout:", self.spin_idle)

        # Pattern Observation Days
        self.spin_obs_days = QSpinBox()
        self.spin_obs_days.setRange(1, 365)
        self.spin_obs_days.setValue(config.patterns.minimum_observation_days)
        self.spin_obs_days.setSuffix(" days")
        form.addRow("Habit Learning Period:", self.spin_obs_days)

        # Pattern Frequency Threshold
        self.spin_threshold = QDoubleSpinBox()
        self.spin_threshold.setRange(0.1, 1.0)
        self.spin_threshold.setSingleStep(0.05)
        self.spin_threshold.setValue(config.patterns.launch_frequency_threshold)
        form.addRow("Habit Frequency Threshold:", self.spin_threshold)

        # Memory Threshold
        self.spin_mem_thresh = QDoubleSpinBox()
        self.spin_mem_thresh.setRange(1.0, 100.0)
        self.spin_mem_thresh.setValue(config.resources.high_memory_percent)
        self.spin_mem_thresh.setSuffix("%")
        form.addRow("High Memory Alert Threshold:", self.spin_mem_thresh)

        # Windows Sign-in Startup Toggle
        from desktop_intelligence.platform.windows_startup import is_run_at_startup_enabled
        self.check_startup = QCheckBox("Start Desktop Intelligence automatically on Windows sign-in")
        self.check_startup.setStyleSheet("font-size: 13px; font-weight: 500;")
        try:
            self.check_startup.setChecked(is_run_at_startup_enabled())
        except Exception:
            self.check_startup.setChecked(False)
        form.addRow("Windows Startup:", self.check_startup)

        pref_box.addLayout(form)

        # Save Button & Status
        btn_bar = QHBoxLayout()
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setObjectName("primary_btn")
        self.save_btn.clicked.connect(self._on_save)
        self.save_status = QLabel("")
        self.save_status.setStyleSheet("color: #34D399; font-size: 11px; font-weight: 600;")
        btn_bar.addWidget(self.save_btn)
        btn_bar.addWidget(self.save_status)
        btn_bar.addStretch()
        pref_box.addLayout(btn_bar)

        layout.addWidget(pref_card)

        # Diagnostics & Paths Section Card
        diag_card = QFrame()
        diag_card.setObjectName("glass_card")
        diag_box = QVBoxLayout(diag_card)
        diag_box.setContentsMargins(18, 16, 18, 16)
        diag_box.setSpacing(10)

        diag_title = QLabel("System Diagnostics & File Locations")
        diag_title.setObjectName("section_title")
        diag_box.addWidget(diag_title)

        diag_form = QFormLayout()
        diag_form.setSpacing(8)
        diag_form.addRow("Data Directory:", QLabel(str(paths.data_dir)))
        diag_form.addRow("Log Directory:", QLabel(str(paths.log_dir)))
        diag_form.addRow("Config File:", QLabel(str(paths.config_file)))
        diag_box.addLayout(diag_form)

        layout.addWidget(diag_card)
        layout.addStretch()

    def _on_save(self) -> None:
        self.config.general.log_level = self.combo_log_level.currentText()
        self.config.ui.theme = self.combo_theme.currentText()
        selected_data = self.combo_accent.currentData()
        if selected_data:
            self.config.ui.accent_color = str(selected_data)
        elif "(" in self.combo_accent.currentText():
            self.config.ui.accent_color = self.combo_accent.currentText().split("(")[-1].split(")")[0].strip()
        self.config.collection.idle_timeout_seconds = self.spin_idle.value()
        self.config.patterns.minimum_observation_days = self.spin_obs_days.value()
        self.config.patterns.launch_frequency_threshold = round(self.spin_threshold.value(), 2)
        self.config.resources.high_memory_percent = round(self.spin_mem_thresh.value(), 1)

        try:
            from desktop_intelligence.platform.windows_startup import set_run_at_startup
            set_run_at_startup(self.check_startup.isChecked())
        except Exception:
            pass

        if self.on_save_config:
            self.on_save_config(self.config)

        self.save_status.setText("Settings saved successfully.")
