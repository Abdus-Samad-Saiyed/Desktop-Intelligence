"""Main Application Window for Desktop Intelligence."""

import os
from pathlib import Path
from typing import Optional
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)
import pandas as pd

from desktop_intelligence.analytics.clean import clean_sessions_df, clean_samples_df
from desktop_intelligence.analytics.recommendations import generate_recommendations
from desktop_intelligence.collectors.application_inventory import ApplicationInventoryScanner
from desktop_intelligence.collectors.system_errors import query_recent_application_errors
from desktop_intelligence.config import AppConfig, save_config
from desktop_intelligence.models import (
    AutomationLogRecord,
    InventoryItem,
    RecommendationRecord,
    format_utc_iso,
    now_utc,
)
from desktop_intelligence.paths import ResolvedPaths
from desktop_intelligence.storage.csv_store import CsvStore
from desktop_intelligence.ui.pages.overview import OverviewPage
from desktop_intelligence.ui.pages.usage import UsagePage
from desktop_intelligence.ui.pages.health import HealthPage
from desktop_intelligence.ui.pages.applications import ApplicationsPage
from desktop_intelligence.ui.pages.automation import AutomationPage
from desktop_intelligence.ui.pages.settings import SettingsPage
from desktop_intelligence.ui.health_summary import summarise_health
from desktop_intelligence.ui.theme import generate_stylesheet, get_effective_theme


class DataLoaderWorker(QThread):
    """Background worker loading CSV data and calculating analytics off the UI thread."""
    data_loaded = Signal(object, object, object, object, object, str)

    def __init__(self, store: CsvStore, config: AppConfig, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.store = store
        self.config = config

    def run(self) -> None:
        try:
            # 1. Read Sessions
            raw_sessions = self.store.read_dataframe("activity_sessions", self.store.paths.activity_sessions_csv)
            sessions_df = clean_sessions_df(raw_sessions)

            # 2. Read Samples
            raw_samples = self.store.read_dataframe("resource_samples", self.store.paths.resource_samples_csv)
            samples_df = clean_samples_df(raw_samples)

            # 3. Read Inventory
            raw_inv = self.store.read_rows("application_inventory", self.store.paths.application_inventory_csv)
            inventory_items = [InventoryItem.from_row(r) for r in raw_inv]

            # 4. Read Recommendations
            raw_recs = self.store.read_rows("recommendations", self.store.paths.recommendations_csv)
            recs = [RecommendationRecord.from_row(r) for r in raw_recs]

            # 5. Read Automation Logs
            raw_logs = self.store.read_rows("automation_log", self.store.paths.automation_log_csv)
            logs = [AutomationLogRecord.from_row(r) for r in raw_logs]

            # Pre-warm Windows reliability events cache in background worker thread
            try:
                query_recent_application_errors(max_records=30)
            except Exception:
                pass

            # Calculate actual data freshness from newest recorded activity
            freshness = "No data yet"
            max_dt = None
            if not sessions_df.empty:
                col = "start_ts_utc" if "start_ts_utc" in sessions_df.columns else ("start_time_utc" if "start_time_utc" in sessions_df.columns else None)
                if col:
                    try:
                        ts_series = pd.to_datetime(sessions_df[col], utc=True, errors="coerce").dropna()
                        if not ts_series.empty:
                            max_dt = ts_series.max().to_pydatetime()
                    except Exception:
                        pass

            if not samples_df.empty and "sample_ts_utc" in samples_df.columns:
                try:
                    ts_series2 = pd.to_datetime(samples_df["sample_ts_utc"], utc=True, errors="coerce").dropna()
                    if not ts_series2.empty:
                        dt2 = ts_series2.max().to_pydatetime()
                        if max_dt is None or dt2 > max_dt:
                            max_dt = dt2
                except Exception:
                    pass

            if max_dt:
                age_secs = (now_utc() - max_dt).total_seconds()
                if age_secs < 120:
                    freshness = "Up to date"
                elif age_secs < 3600:
                    freshness = f"{int(age_secs // 60)} min ago"
                elif age_secs < 86400:
                    freshness = f"{int(age_secs // 3600)} hrs ago"
                else:
                    freshness = "Stale (> 1d)"

            self.data_loaded.emit(sessions_df, samples_df, inventory_items, recs, logs, freshness)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("DataLoaderWorker error: %s", exc)
            self.data_loaded.emit(pd.DataFrame(), pd.DataFrame(), [], [], [], "No data yet")


class MainWindow(QMainWindow):
    """Desktop Intelligence Main Application Dashboard."""

    def __init__(
        self,
        config: AppConfig,
        paths: ResolvedPaths,
        store: CsvStore,
        health_provider: Optional[object] = None,
        is_demo_mode: bool = False,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.config = config
        self.paths = paths
        self.store = store
        self.health_provider = health_provider
        self.is_demo_mode = is_demo_mode

        self._last_sessions_df: pd.DataFrame = pd.DataFrame()
        self._last_recs: list = []
        self._last_freshness: str = "Up to date"

        self.setWindowTitle("Desktop Intelligence [DEMO MODE]" if self.is_demo_mode else "Desktop Intelligence")
        self.setMinimumSize(980, 660)
        self.resize(1120, 740)

        central_widget = QWidget()
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Left Sidebar Navigation Container
        sidebar_widget = QWidget()
        sidebar_widget.setFixedWidth(220)
        sidebar_widget.setObjectName("sidebar_container")
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        # Brand header at top of sidebar
        brand_widget = QWidget()
        brand_layout = QVBoxLayout(brand_widget)
        brand_layout.setContentsMargins(18, 18, 18, 10)
        brand_layout.setSpacing(2)
        brand_title = QLabel("Desktop Intelligence")
        brand_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #F0F6FC;")
        brand_sub = QLabel("Local Activity & AI")
        brand_sub.setStyleSheet("font-size: 11px; color: #8B949E;")
        brand_layout.addWidget(brand_title)
        brand_layout.addWidget(brand_sub)
        sidebar_layout.addWidget(brand_widget)

        # Left Sidebar Navigation List
        self.nav_list = QListWidget()
        self.nav_list.setObjectName("nav_list")
        self.nav_list.addItem("Overview")
        self.nav_list.addItem("Usage Analytics")
        self.nav_list.addItem("System Health")
        self.nav_list.addItem("Applications")
        self.nav_list.addItem("Automation")
        self.nav_list.addItem("Settings")
        self.nav_list.currentRowChanged.connect(self._on_page_changed)
        sidebar_layout.addWidget(self.nav_list, stretch=1)

        # Footer multi-source status indicators in sidebar
        footer_widget = QWidget()
        footer_layout = QVBoxLayout(footer_widget)
        footer_layout.setContentsMargins(18, 10, 18, 14)
        footer_layout.setSpacing(5)

        footer_title = QLabel("COLLECTOR HEALTH")
        footer_title.setStyleSheet("font-size: 10px; font-weight: 600; color: #64748B; letter-spacing: 0.5px;")
        footer_layout.addWidget(footer_title)

        self.status_hook = QLabel("● Foreground Hook: Active")
        self.status_hook.setStyleSheet("color: #34D399; font-size: 11px;")
        self.status_hook.setToolTip("Win32 SetWinEventHook foreground focus tracking: Active")

        self.status_process = QLabel("● Process Trace: Active")
        self.status_process.setStyleSheet("color: #34D399; font-size: 11px;")
        self.status_process.setToolTip("WMI / Win32_Process creation event listener: Operational")

        self.status_diag = QLabel("● Diagnostics: Ready")
        self.status_diag.setStyleSheet("color: #22D3EE; font-size: 11px;")
        self.status_diag.setToolTip("Windows Reliability & Error diagnostics: Operational")

        # Keep status_dot alias for backwards compatibility
        self.status_dot = self.status_hook

        footer_layout.addWidget(self.status_hook)
        footer_layout.addWidget(self.status_process)
        footer_layout.addWidget(self.status_diag)
        sidebar_layout.addWidget(footer_widget)

        main_layout.addWidget(sidebar_widget)

        # Right Stacked Pages and Demo Banner container
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        if self.is_demo_mode:
            self.demo_banner = QFrame()
            self.demo_banner.setObjectName("demo_banner")
            self.demo_banner.setStyleSheet(
                "QFrame#demo_banner { background: rgba(245, 158, 11, 0.15); "
                "border-bottom: 1px solid rgba(245, 158, 11, 0.4); padding: 6px 16px; }"
            )
            banner_box = QHBoxLayout(self.demo_banner)
            banner_box.setContentsMargins(12, 6, 12, 6)
            banner_box.setSpacing(8)
            banner_icon = QLabel("⚡")
            banner_icon.setStyleSheet("font-size: 13px;")
            banner_text = QLabel("DEMO MODE — Operating on isolated simulation data. Real system settings and files are protected.")
            banner_text.setStyleSheet("color: #FBBF24; font-weight: 600; font-size: 12px;")
            banner_box.addWidget(banner_icon)
            banner_box.addWidget(banner_text)
            banner_box.addStretch()
            right_layout.addWidget(self.demo_banner)

        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, stretch=1)
        main_layout.addWidget(right_container, stretch=1)

        # Instantiate pages
        self.page_overview = OverviewPage(
            on_rec_action=self._handle_recommendation_action,
            on_navigate_health=lambda: self.nav_list.setCurrentRow(2),
        )
        self.page_usage = UsagePage()
        self.page_health = HealthPage()
        self.page_apps = ApplicationsPage()
        self.page_automation = AutomationPage(on_toggle_automation=self._handle_toggle_automation)
        self.page_settings = SettingsPage(
            config=self.config, paths=self.paths, on_save_config=self._handle_save_config
        )

        self.stack.addWidget(self.page_overview)
        self.stack.addWidget(self.page_usage)
        self.stack.addWidget(self.page_health)
        self.stack.addWidget(self.page_apps)
        self.stack.addWidget(self.page_automation)
        self.stack.addWidget(self.page_settings)

        # Single-flight refresh tracking
        self._active_worker: Optional[DataLoaderWorker] = None
        self._refresh_pending: bool = False
        self._is_quitting: bool = False

        # Setup System Tray
        self._setup_tray_icon()

        # Apply design system stylesheet and theme
        self.apply_theme(self.config.ui.theme, self.config.ui.accent_color)

        # Periodic refresh timer (every 10 seconds)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.trigger_refresh)
        self.refresh_timer.start(10000)

        # Initial data load
        self.trigger_refresh()

    def _setup_tray_icon(self) -> None:
        self.tray_icon = None
        if not getattr(self.config.ui, "show_tray_icon", True):
            return
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        style = QApplication.style()
        icon = style.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip("Desktop Intelligence")

        tray_menu = QMenu(self)
        show_action = QAction("Open Dashboard", self)
        show_action.triggered.connect(self._restore_from_tray)
        tray_menu.addAction(show_action)

        refresh_action = QAction("Refresh Data", self)
        refresh_action.triggered.connect(self.trigger_refresh)
        tray_menu.addAction(refresh_action)

        tray_menu.addSeparator()

        quit_action = QAction("Exit", self)
        quit_action.triggered.connect(self._quit_application)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible():
                if self.isMinimized():
                    self.showNormal()
                self.activateWindow()
                self.raise_()
            else:
                self._restore_from_tray()

    def _quit_application(self) -> None:
        self._is_quitting = True
        if self.tray_icon:
            self.tray_icon.hide()
        QApplication.quit()

    def closeEvent(self, event) -> None:
        if (
            getattr(self, "tray_icon", None)
            and self.tray_icon.isVisible()
            and not getattr(self, "_is_quitting", False)
        ):
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                "Desktop Intelligence",
                "Application is still running in the background. Access it from the system tray.",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )
        else:
            if hasattr(self, "refresh_timer"):
                self.refresh_timer.stop()
            event.accept()

    def _on_page_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(index)

    def trigger_refresh(self) -> None:
        """Trigger background data load without blocking Qt thread with single-flight worker."""
        if getattr(self, "_active_worker", None) is not None and self._active_worker.isRunning():
            self._refresh_pending = True
            return

        self._refresh_pending = False
        self._active_worker = DataLoaderWorker(self.store, self.config, self)
        self.worker = self._active_worker  # Preserve for backwards-compatibility with tests inspecting self.worker
        self._active_worker.data_loaded.connect(self._on_data_loaded)
        self._active_worker.finished.connect(self._on_worker_finished)
        self._active_worker.finished.connect(self._active_worker.deleteLater)
        self._active_worker.start()

    def _on_worker_finished(self) -> None:
        self._active_worker = None
        if getattr(self, "_refresh_pending", False):
            self.trigger_refresh()

    def update_collector_health(self) -> str:
        """Update sidebar status indicators from real collector health and return collection status."""
        collection_status = "Operational (Active)"
        if self.health_provider:
            try:
                health_dict = self.health_provider() if callable(self.health_provider) else getattr(self.health_provider, "get_health_status", lambda: {})()
            except Exception:
                health_dict = {}

            summary = summarise_health(health_dict)
            self._current_health_summary = summary
            collection_status = summary.overall_status

            if "foreground" in health_dict:
                h = health_dict["foreground"]
                st = getattr(h, "state", "stopped")
                msg = getattr(h, "message", "")
                if st == "active":
                    self.status_hook.setText("● Foreground Hook: Active")
                    self.status_hook.setStyleSheet("color: #34D399; font-size: 11px;")
                elif st == "degraded":
                    self.status_hook.setText("● Foreground Hook: Degraded")
                    self.status_hook.setStyleSheet("color: #FBBF24; font-size: 11px;")
                elif st == "failed":
                    self.status_hook.setText("● Foreground Hook: Failed")
                    self.status_hook.setStyleSheet("color: #FB7185; font-size: 11px;")
                elif st == "disabled":
                    self.status_hook.setText("● Foreground Hook: Disabled")
                    self.status_hook.setStyleSheet("color: #64748B; font-size: 11px;")
                else:
                    self.status_hook.setText(f"● Foreground Hook: {st.capitalize()}")
                    self.status_hook.setStyleSheet("color: #64748B; font-size: 11px;")
                self.status_hook.setToolTip(f"Foreground Hook: {msg}")

            if "process" in health_dict:
                h = health_dict["process"]
                st = getattr(h, "state", "stopped")
                msg = getattr(h, "message", "")
                if st == "active":
                    self.status_process.setText("● Process Trace: Active")
                    self.status_process.setStyleSheet("color: #34D399; font-size: 11px;")
                elif st == "degraded":
                    self.status_process.setText("● Process Trace: Degraded")
                    self.status_process.setStyleSheet("color: #FBBF24; font-size: 11px;")
                elif st in ("failed", "unavailable"):
                    self.status_process.setText(f"● Process Trace: {st.capitalize()}")
                    self.status_process.setStyleSheet("color: #FB7185; font-size: 11px;")
                elif st == "disabled":
                    self.status_process.setText("● Process Trace: Disabled")
                    self.status_process.setStyleSheet("color: #64748B; font-size: 11px;")
                else:
                    self.status_process.setText(f"● Process Trace: {st.capitalize()}")
                    self.status_process.setStyleSheet("color: #64748B; font-size: 11px;")
                self.status_process.setToolTip(f"Process Trace: {msg}")

        return collection_status

    def _on_data_loaded(
        self,
        sessions_df: pd.DataFrame,
        samples_df: pd.DataFrame,
        inventory_items: list,
        recommendations: list,
        logs: list,
        freshness: str,
    ) -> None:
        """Dispatch loaded data to respective pages."""
        self._last_sessions_df = sessions_df
        self._last_recs = recommendations
        self._last_freshness = freshness

        collection_status = self.update_collector_health()

        # Check for system error events on Windows
        errors, diag = query_recent_application_errors(max_records=30)

        # Update Overview
        self.page_overview.update_data(
            sessions_df,
            recommendations,
            freshness_text=freshness,
            collection_status_text=collection_status,
            theme_mode=self.config.ui.theme,
            accent_color=self.config.ui.accent_color,
        )

        # Update Usage
        self.page_usage.update_data(
            sessions_df,
            theme_mode=self.config.ui.theme,
            accent_color=self.config.ui.accent_color,
        )

        # Update Health
        self.page_health.update_data(
            samples_df,
            errors,
            diag,
            self.config.resources,
            health_summary=getattr(self, "_current_health_summary", None),
        )

        # Update Applications
        self.page_apps.update_data(inventory_items)

        # Update Automation
        self.page_automation.update_data(self.config.automation.enabled, recommendations, logs)

        # Update collector status indicators
        if hasattr(self, "status_diag"):
            if diag and (diag.startswith("Operational") or diag.startswith("No recent")):
                self.status_diag.setText("● Diagnostics: Ready")
                self.status_diag.setStyleSheet("color: #22D3EE; font-size: 11px;")
                self.status_diag.setToolTip(f"Windows Event Logs: {diag}")
            else:
                self.status_diag.setText("● Diagnostics: Standby")
                self.status_diag.setStyleSheet("color: #FBBF24; font-size: 11px;")
                self.status_diag.setToolTip(f"Windows Event Logs: {diag}")

    def apply_theme(self, theme_mode: Optional[str] = None, accent_color: Optional[str] = None) -> None:
        """Apply theme mode and accent color dynamically to the window and child pages."""
        if theme_mode is not None:
            self.config.ui.theme = theme_mode
        if accent_color is not None:
            self.config.ui.accent_color = accent_color

        stylesheet = generate_stylesheet(self.config.ui.theme, self.config.ui.accent_color)
        self.setStyleSheet(stylesheet)

        # Refresh page visuals with the new theme
        if hasattr(self, "page_overview") and hasattr(self, "_last_sessions_df"):
            self.page_overview.update_data(
                self._last_sessions_df,
                self._last_recs,
                self._last_freshness,
                theme_mode=self.config.ui.theme,
                accent_color=self.config.ui.accent_color,
            )
        if hasattr(self, "page_usage") and hasattr(self, "_last_sessions_df"):
            self.page_usage.update_data(
                self._last_sessions_df,
                theme_mode=self.config.ui.theme,
                accent_color=self.config.ui.accent_color,
            )

    def _handle_recommendation_action(self, rec_id: str, new_status: str) -> None:
        """Update recommendation status in recommendations.csv."""
        raw_recs = self.store.read_rows("recommendations", self.paths.recommendations_csv)
        updated = False
        for r in raw_recs:
            if r.get("recommendation_id") == rec_id:
                r["status"] = new_status
                updated = True
                break

        if updated:
            from desktop_intelligence.models import SCHEMAS
            self.store.replace_all(
                "recommendations",
                self.paths.recommendations_csv,
                [[row_dict[c] for c in SCHEMAS["recommendations"]] for row_dict in raw_recs],
            )
            self.trigger_refresh()

    def _handle_toggle_automation(self, enabled: bool) -> None:
        self.config.automation.enabled = enabled
        self._persist_config()
        self.trigger_refresh()

    def _handle_save_config(self, new_cfg: AppConfig) -> None:
        self.config = new_cfg
        self.apply_theme(new_cfg.ui.theme, new_cfg.ui.accent_color)
        self._persist_config()
        self.trigger_refresh()

    def _persist_config(self) -> None:
        """Serialize configuration changes back to config.toml safely and atomically."""
        if self.is_demo_mode:
            # Protected in demo mode: do not write to user's real configuration
            return
        try:
            save_config(self.config, self.paths.config_file)
        except Exception as exc:
            QMessageBox.warning(self, "Save Error", f"Failed to persist config: {exc}")

    def _render_toml(self) -> str:
        lines = [
            "# Desktop Intelligence - Configuration File",
            "",
            "[general]",
            f'app_name = "{self.config.general.app_name}"',
            f'config_version = {self.config.general.config_version}',
            f'log_level = "{self.config.general.log_level}"',
            f'timezone = "{self.config.general.timezone}"',
            "",
            "[paths]",
            f'data_dir = "{self.config.paths.data_dir}"',
            f'log_dir = "{self.config.paths.log_dir}"',
            "",
            "[collection]",
            f'enable_process_start_events = {str(self.config.collection.enable_process_start_events).lower()}',
            f'enable_foreground_events = {str(self.config.collection.enable_foreground_events).lower()}',
            f'enable_application_inventory = {str(self.config.collection.enable_application_inventory).lower()}',
            f'enable_system_error_events = {str(self.config.collection.enable_system_error_events).lower()}',
            f'idle_timeout_seconds = {self.config.collection.idle_timeout_seconds}',
            f'idle_check_interval_seconds = {self.config.collection.idle_check_interval_seconds}',
            f'resource_snapshot_on_process_start = {str(self.config.collection.resource_snapshot_on_process_start).lower()}',
            f'resource_snapshot_on_foreground_change = {str(self.config.collection.resource_snapshot_on_foreground_change).lower()}',
            f'collect_window_titles = {str(self.config.collection.collect_window_titles).lower()}',
            "",
            "[retention]",
            f'events_days = {self.config.retention.events_days}',
            f'sessions_days = {self.config.retention.sessions_days}',
            f'resource_samples_days = {self.config.retention.resource_samples_days}',
            "",
            "[patterns]",
            f'minimum_observation_days = {self.config.patterns.minimum_observation_days}',
            f'minimum_context_occurrences = {self.config.patterns.minimum_context_occurrences}',
            f'launch_frequency_threshold = {self.config.patterns.launch_frequency_threshold:.2f}',
            f'time_bucket_minutes = {self.config.patterns.time_bucket_minutes}',
            f'eligible_day_types = {list(self.config.patterns.eligible_day_types)!r}',
            "",
            "[resources]",
            f'high_memory_percent = {self.config.resources.high_memory_percent:.1f}',
            f'high_system_memory_percent = {self.config.resources.high_system_memory_percent:.1f}',
            f'high_cpu_percent = {self.config.resources.high_cpu_percent:.1f}',
            f'sustained_observation_count = {self.config.resources.sustained_observation_count}',
            "",
            "[automation]",
            f'enabled = {str(self.config.automation.enabled).lower()}',
            f'require_rule_approval = {str(self.config.automation.require_rule_approval).lower()}',
            f'prompt_timeout_seconds = {self.config.automation.prompt_timeout_seconds}',
            f'no_response_action = "{self.config.automation.no_response_action}"',
            f'prevent_duplicate_instances = {str(self.config.automation.prevent_duplicate_instances).lower()}',
            f'launch_missed_window_seconds = {self.config.automation.launch_missed_window_seconds}',
            "",
            "[ui]",
            f'theme = "{self.config.ui.theme}"',
            f'accent_color = "{self.config.ui.accent_color}"',
            f'start_minimized = {str(self.config.ui.start_minimized).lower()}',
            f'show_tray_icon = {str(self.config.ui.show_tray_icon).lower()}',
            "",
            "[llm]",
            f'enabled = {str(self.config.llm.enabled).lower()}',
            f'provider = "{self.config.llm.provider}"',
            f'share_raw_events = {str(self.config.llm.share_raw_events).lower()}',
        ]
        return "\n".join(lines) + "\n"
