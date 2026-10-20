"""Desktop Intelligence application lifecycle and entry point coordinator."""

import argparse
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import signal
import sys
import threading
import time
from typing import Dict, List, Optional, Set

from desktop_intelligence.analytics.clean import clean_sessions_df, clean_samples_df
from desktop_intelligence.analytics.recommendations import generate_recommendations
from desktop_intelligence.automation.launcher import SafeProcessLauncher
from desktop_intelligence.automation.rules import sync_rules_from_recommendations
from desktop_intelligence.automation.scheduler import AutomationScheduler
from desktop_intelligence.collectors.activity_manager import ActivityManager
from desktop_intelligence.collectors.application_inventory import ApplicationInventoryScanner
from desktop_intelligence.collectors.base import SystemClock
from desktop_intelligence.collectors.foreground_events import WindowsForegroundHook
from desktop_intelligence.collectors.windows_process_events import WindowsProcessStartListener
from desktop_intelligence.collectors.system_errors import query_recent_application_errors
from desktop_intelligence.config import AppConfig, load_config
from desktop_intelligence.logging_setup import setup_logging
from desktop_intelligence.models import (
    InventoryItem,
    RecommendationRecord,
    format_utc_iso,
    now_utc,
)
from desktop_intelligence.paths import ResolvedPaths, resolve_paths
from desktop_intelligence.storage.csv_store import CsvStore

logger = logging.getLogger("desktop_intelligence")


class DesktopIntelligenceApp:
    """Coordinates lifecycle of storage, background collectors, scheduler, and UI."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        paths: Optional[ResolvedPaths] = None,
        store: Optional[CsvStore] = None,
        config: Optional[AppConfig] = None,
    ):
        if paths is not None:
            self.paths = paths
        else:
            self.paths = resolve_paths(config_file_override=config_path)
        self.paths.ensure_directories()

        if config is not None:
            self.config = config
        else:
            self.config = load_config(self.paths.config_file, fallback_on_missing=True)
            if self.config.paths.data_dir or self.config.paths.log_dir:
                self.paths = resolve_paths(config_file_override=config_path, config=self.config)
                self.paths.ensure_directories()
        setup_logging(self.paths.log_dir, self.config.general.log_level)

        self.clock = SystemClock()
        self.store = store or CsvStore(self.paths)

        # Initialize event sources
        event_sources = []
        if self.config.collection.enable_foreground_events and sys.platform == "win32":
            self.foreground_hook = WindowsForegroundHook(callback=self._on_raw_event, clock=self.clock)
            event_sources.append(self.foreground_hook)
        else:
            self.foreground_hook = None

        if self.config.collection.enable_process_start_events and sys.platform == "win32":
            self.process_listener = WindowsProcessStartListener(callback=self._on_raw_event, clock=self.clock)
            event_sources.append(self.process_listener)
        else:
            self.process_listener = None

        self.activity_manager = ActivityManager(
            config=self.config,
            store=self.store,
            clock=self.clock,
            event_sources=event_sources,
        )

        self.scheduler = AutomationScheduler(
            config=self.config,
            store=self.store,
            launcher=SafeProcessLauncher(allowlist_provider=self.get_launcher_allowlist),
            clock=self.clock,
        )

        self._running = False
        self._periodic_thread: Optional[threading.Thread] = None
        self.is_demo_mode: bool = False

    def get_launcher_allowlist(self) -> Set[str]:
        """Return set of normalized executable paths and binary names from inventory and activity."""
        allowlist: Set[str] = set()
        try:
            inv = self.store.read_rows("application_inventory", self.paths.application_inventory_csv)
            for r in inv:
                exe = (r.get("exe_path") or "").strip().lower()
                if exe:
                    allowlist.add(os.path.normpath(exe))
                    allowlist.add(Path(exe).name.lower())
                d_name = (r.get("display_name") or "").strip().lower()
                if d_name:
                    allowlist.add(d_name)

            evts = self.store.read_dataframe("activity_events", self.paths.activity_events_csv)
            if not evts.empty and "exe_path" in evts.columns:
                for exe in evts["exe_path"].dropna().unique():
                    norm = os.path.normpath(str(exe)).strip().lower()
                    if norm:
                        allowlist.add(norm)
                        allowlist.add(Path(norm).name.lower())
        except Exception as exc:
            logger.debug("Failed building launcher allowlist: %s", exc)
        return allowlist

    def _on_raw_event(self, event) -> None:
        self.activity_manager.on_event(event)

    def start_background_services(self) -> None:
        """Start background activity collection, inventory scan, and scheduler."""
        if self._running:
            return
        self._running = True

        if self.is_demo_mode:
            logger.info("Demo mode: running with simulated background services.")
            if self.foreground_hook:
                self.foreground_hook.health_state = "active"
                self.foreground_hook.status_message = "Active (Demo Simulation)"
            if self.process_listener:
                self.process_listener.health_state = "active"
                self.process_listener.status_message = "Active (Demo Simulation)"
            return

        logger.info("Starting Desktop Intelligence background services...")

        # 1. Start Activity Manager (hooks and queue)
        self.activity_manager.start()

        # 2. Perform initial application inventory discovery if needed
        if self.config.collection.enable_application_inventory:
            self.refresh_inventory()

        # 3. Synchronize approved automation rules
        self.refresh_automation_rules()

        # 4. Prune records exceeding retention limits
        self.prune_retention()

        # 5. Start background periodic worker for scheduler and analytics cycles
        self._periodic_thread = threading.Thread(
            target=self._periodic_loop, daemon=True, name="BackgroundPeriodicWorker"
        )
        self._periodic_thread.start()

        logger.info("Background services operational.")

    def run_analytics_cycle(self) -> List[RecommendationRecord]:
        """Run data cleaning, generate recommendations, sync rules, and prune retention."""
        raw_sessions = self.store.read_dataframe("activity_sessions", self.paths.activity_sessions_csv)
        sessions_df = clean_sessions_df(raw_sessions)

        raw_samples = self.store.read_dataframe("resource_samples", self.paths.resource_samples_csv)
        samples_df = clean_samples_df(raw_samples)

        raw_inv = self.store.read_rows("application_inventory", self.paths.application_inventory_csv)
        inventory_items = [InventoryItem.from_row(r) for r in raw_inv]

        new_recs = generate_recommendations(
            config=self.config,
            store=self.store,
            sessions_df=sessions_df,
            samples_df=samples_df,
            inventory_items=inventory_items,
            clock=self.clock,
        )

        self.refresh_automation_rules()
        self.prune_retention()
        return new_recs

    def _periodic_loop(self) -> None:
        """Periodic background execution for automation evaluation and analytics refresh."""
        last_analytics_ts = time.time()
        while self._running:
            try:
                # Evaluate automation rules
                if self.config.automation.enabled:
                    self.scheduler.evaluate_and_trigger()

                # Run analytics cycle every 15 minutes (900s)
                if (time.time() - last_analytics_ts) >= 900.0:
                    last_analytics_ts = time.time()
                    self.run_analytics_cycle()
            except Exception as exc:
                logger.error("Error in background periodic loop: %s", exc)

            # Sleep in 1s slices to respond swiftly to stop()
            for _ in range(15):
                if not self._running:
                    break
                time.sleep(1.0)

    def prune_retention(self) -> dict:
        """Prune records older than configured retention limits."""
        res = self.store.prune_retention(
            events_days=self.config.retention.events_days,
            sessions_days=self.config.retention.sessions_days,
            samples_days=self.config.retention.resource_samples_days,
        )
        if any(v > 0 for v in res.values()):
            logger.info("Retention pruning completed: %s", res)
        return res

    def stop_background_services(self) -> None:
        """Stop background services and flush all queues cleanly."""
        if not self._running:
            return
        logger.info("Stopping Desktop Intelligence background services...")
        self._running = False
        if self._periodic_thread and self._periodic_thread.is_alive():
            self._periodic_thread.join(timeout=2.0)
        self.activity_manager.stop()
        logger.info("Background services stopped cleanly.")

    def get_health_status(self) -> dict:
        """Return structured health states for active collectors."""
        from desktop_intelligence.collectors.base import CollectorHealth
        status = {}
        if self.foreground_hook:
            status["foreground"] = self.foreground_hook.health()
        else:
            status["foreground"] = CollectorHealth(
                name="Foreground Hook",
                state="disabled",
                message="Disabled in configuration",
            )

        if self.process_listener:
            status["process"] = self.process_listener.health()
        else:
            status["process"] = CollectorHealth(
                name="Process Trace",
                state="disabled",
                message="Disabled in configuration",
            )

        return status

    def refresh_inventory(self) -> List[InventoryItem]:
        """Scan installed applications and update application_inventory.csv."""
        scanner = getattr(self, "inventory_scanner", None) or ApplicationInventoryScanner(clock=self.clock)

        # Correlate with launch counts and last launches
        counts: Dict[str, int] = {}
        last_launches: Dict[str, str] = {}

        # 1. From activity events (process_start)
        events = self.store.read_dataframe("activity_events", self.paths.activity_events_csv)
        if not events.empty and "event_type" in events.columns:
            start_events = events[events["event_type"] == "process_start"]
            for _, row in start_events.iterrows():
                p_name = str(row.get("process_name", "")).lower().strip()
                exe = str(row.get("exe_path", "")).lower().strip()
                ts = str(row.get("event_ts_utc", "")).strip()

                keys = set()
                if p_name:
                    keys.add(p_name)
                if exe:
                    keys.add(exe)
                    keys.add(Path(exe).name.lower())

                for k in keys:
                    counts[k] = counts.get(k, 0) + 1
                    if ts and (k not in last_launches or ts > last_launches[k]):
                        last_launches[k] = ts

        # Existing first seen timestamps
        existing_rows = self.store.read_rows("application_inventory", self.paths.application_inventory_csv)
        first_seen_map = {r["display_name"].lower(): r["first_seen_ts_utc"] for r in existing_rows}

        items = scanner.build_inventory(
            observed_launch_counts=counts,
            last_launch_timestamps=last_launches,
            existing_first_seen=first_seen_map,
        )

        # Overwrite inventory file with fresh snapshot atomically
        self.store.replace_all(
            "application_inventory",
            self.paths.application_inventory_csv,
            [item.to_row() for item in items],
        )

        logger.info("Application inventory updated with %d installed items.", len(items))
        return items

    def refresh_automation_rules(self) -> None:
        """Load approved recommendations into the scheduler."""
        raw_recs = self.store.read_rows("recommendations", self.paths.recommendations_csv)
        recs = [RecommendationRecord.from_row(r) for r in raw_recs]

        raw_inv = self.store.read_rows("application_inventory", self.paths.application_inventory_csv)
        inventory = [InventoryItem.from_row(r) for r in raw_inv]

        rules = sync_rules_from_recommendations(recs, inventory)
        self.scheduler.set_rules(rules)

    def print_diagnostics(self) -> None:
        """Output detailed diagnostic health status."""
        print("=" * 60)
        print("DESKTOP INTELLIGENCE - DIAGNOSTIC REPORT")
        print("=" * 60)
        print(f"Platform:              {sys.platform} ({os.name})")
        print(f"Python Executable:     {sys.executable}")
        print(f"Python Version:        {sys.version.split()[0]}")
        print(f"Base Directory:        {self.paths.base_dir}")
        print(f"Data Directory:        {self.paths.data_dir}")
        print(f"Log Directory:         {self.paths.log_dir}")
        print(f"Config File:           {self.paths.config_file}")
        print(f"Config Exists:         {self.paths.config_file.exists()}")

        # Record counts
        for name, prop in [
            ("Activity Events", self.paths.activity_events_csv),
            ("Activity Sessions", self.paths.activity_sessions_csv),
            ("Resource Samples", self.paths.resource_samples_csv),
            ("Application Inventory", self.paths.application_inventory_csv),
            ("Recommendations", self.paths.recommendations_csv),
            ("Automation Log", self.paths.automation_log_csv),
        ]:
            if prop.exists():
                count = max(0, len(prop.read_text(encoding="utf-8").splitlines()) - 1)
                size_kb = prop.stat().st_size / 1024.0
                print(f"{name:22} {count:6d} records ({size_kb:6.1f} KB)")
            else:
                print(f"{name:22} Not created yet")

        # Collector status
        print("-" * 60)
        fg_status = self.foreground_hook.status_message if self.foreground_hook else "Disabled in configuration"
        wmi_status = self.process_listener.status_message if self.process_listener else "Disabled in configuration"
        print(f"Foreground Hook:       {fg_status}")
        print(f"Process Start Watcher: {wmi_status}")

        # Errors status
        _, error_diag = query_recent_application_errors(max_records=5)
        print(f"Application Errors:    {error_diag}")
        print("=" * 60)


class SingleInstanceGuard:
    """Ensures only a single instance of Desktop Intelligence runs on the system."""

    def __init__(self, mutex_name: str = "Local\\DesktopIntelligence_SingleInstance_Mutex"):
        self.mutex_name = mutex_name
        self.handle = None
        self.is_primary = False

    def acquire(self) -> bool:
        if sys.platform == "win32":
            import ctypes
            ERROR_ALREADY_EXISTS = 183
            self.handle = ctypes.windll.kernel32.CreateMutexW(None, True, self.mutex_name)
            last_err = ctypes.windll.kernel32.GetLastError()
            if last_err == ERROR_ALREADY_EXISTS:
                if self.handle:
                    ctypes.windll.kernel32.CloseHandle(self.handle)
                    self.handle = None
                self.is_primary = False
                return False
            self.is_primary = True
            return True
        self.is_primary = True
        return True

    def release(self) -> None:
        if sys.platform == "win32" and self.handle:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None
        self.is_primary = False


def main(argv: Optional[List[str]] = None) -> int:
    """CLI and application entry point."""
    parser = argparse.ArgumentParser(description="Desktop Intelligence: Application usage, analytics, and automation.")
    parser.add_argument("--diagnostics", action="store_true", help="Print system diagnostics and data status")
    parser.add_argument("--rescan-inventory", action="store_true", help="Perform application inventory discovery scan")
    parser.add_argument("--collector-only", "--headless", action="store_true", help="Run background collector without GUI")
    parser.add_argument("--demo-mode", action="store_true", help="Launch in isolated demo mode with deterministic simulated data")
    parser.add_argument("--consent-prompt", action="store_true", help="Display standalone consent dialog for automation rule")
    parser.add_argument("--rule-id", type=str, default="", help="Automation rule ID for consent prompt")
    parser.add_argument("--app-name", type=str, default="", help="Application name for consent prompt")
    parser.add_argument("--exe-path", type=str, default="", help="Executable path for consent prompt")
    parser.add_argument("--day", type=str, default="", help="Day of week for consent prompt")
    parser.add_argument("--time", type=str, default="", help="Time bucket for consent prompt")
    parser.add_argument("--timeout", type=int, default=10, help="Consent prompt timeout in seconds")
    parser.add_argument("--config", type=Path, default=None, help="Custom path to config.toml")

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.consent_prompt:
        from PySide6.QtWidgets import QApplication
        from desktop_intelligence.automation.rules import AutomationRule
        from desktop_intelligence.ui.dialogs.consent_prompt import show_launch_consent_dialog

        qt_app = QApplication.instance()
        if qt_app is None:
            qt_app = QApplication(sys.argv)

        rule = AutomationRule(
            rule_id=args.rule_id or "cli_prompt",
            app_name=args.app_name or "Application",
            exe_path=args.exe_path or "",
            day_of_week=args.day or "",
            time_bucket=args.time or "",
            frequency_percent=100.0,
            approved=True,
        )
        choice = show_launch_consent_dialog(rule, timeout_seconds=args.timeout or 10)
        print(choice)
        return 0 if choice == "approve" else 1

    if args.demo_mode:
        import tempfile
        from desktop_intelligence.demo_data import seed_demo_data
        demo_dir = Path(tempfile.mkdtemp(prefix="DesktopIntelligence_Demo_"))
        paths = resolve_paths(data_dir_override=str(demo_dir / "data"), log_dir_override=str(demo_dir / "logs"))
        paths.ensure_directories()
        store = CsvStore(paths)
        seed_demo_data(store)
        app = DesktopIntelligenceApp(paths=paths, store=store)
        app.is_demo_mode = True
    else:
        app = DesktopIntelligenceApp(config_path=args.config)

    if args.diagnostics:
        app.print_diagnostics()
        return 0

    if args.rescan_inventory:
        items = app.refresh_inventory()
        print(f"Successfully scanned {len(items)} installed applications.")
        return 0

    from desktop_intelligence.daemon import (
        COLLECTOR_MUTEX_NAME,
        UI_MUTEX_NAME,
        write_daemon_status,
        remove_daemon_status,
        update_heartbeat,
    )

    if args.collector_only:
        collector_guard = SingleInstanceGuard(COLLECTOR_MUTEX_NAME)
        if not collector_guard.acquire():
            logger.warning("Another background collector instance is already running. Exiting.")
            print("Desktop Intelligence collector is already running.", file=sys.stderr)
            return 0

        try:
            write_daemon_status(app.paths, os.getpid(), "running")
            app.start_background_services()

            def handle_sig(sig, frame):
                logger.info("Received termination signal %s. Shutting down...", sig)
                app.stop_background_services()
                remove_daemon_status(app.paths)
                collector_guard.release()
                sys.exit(0)

            signal.signal(signal.SIGINT, handle_sig)
            signal.signal(signal.SIGTERM, handle_sig)

            print("Desktop Intelligence collector running in background. Press Ctrl+C to terminate.")
            try:
                while True:
                    time.sleep(1.0)
                    update_heartbeat(app.paths)
            except KeyboardInterrupt:
                app.stop_background_services()
            return 0
        finally:
            remove_daemon_status(app.paths)
            collector_guard.release()

    # GUI Mode: Acquire UI mutex
    ui_guard = SingleInstanceGuard(UI_MUTEX_NAME)
    if not ui_guard.acquire():
        logger.warning("Another instance of Desktop Intelligence UI is already running. Exiting.")
        print("Desktop Intelligence UI is already running.", file=sys.stderr)
        return 0

    # Probe collector mutex: if held, attach to existing daemon; otherwise host the collector services
    collector_guard = SingleInstanceGuard(COLLECTOR_MUTEX_NAME)
    is_attached = not collector_guard.acquire()

    try:
        if is_attached:
            logger.info("Collector daemon running. Attaching UI to existing background services.")
        else:
            write_daemon_status(app.paths, os.getpid(), "running")
            app.start_background_services()

        def handle_sig_gui(sig, frame):
            logger.info("Received termination signal %s. Shutting down UI...", sig)
            if not is_attached:
                app.stop_background_services()
                remove_daemon_status(app.paths)
                collector_guard.release()
            ui_guard.release()
            sys.exit(0)

        signal.signal(signal.SIGINT, handle_sig_gui)
        signal.signal(signal.SIGTERM, handle_sig_gui)

        # Launch PySide6 GUI Dashboard
        from PySide6.QtWidgets import QApplication
        from desktop_intelligence.ui.main_window import MainWindow

        qt_app = QApplication.instance()
        if qt_app is None:
            qt_app = QApplication(sys.argv)

        window = MainWindow(
            config=app.config,
            paths=app.paths,
            store=app.store,
            health_provider=app.get_health_status,
            is_demo_mode=app.is_demo_mode,
            is_attached=is_attached,
        )

        if not is_attached:
            # Wire thread-safe GUI consent broker
            from desktop_intelligence.ui.consent_broker import ConsentBroker
            consent_broker = ConsentBroker(parent_window=window)
            app.scheduler.consent_provider = consent_broker.request_consent
            window._consent_broker = consent_broker

        if not app.config.ui.start_minimized:
            window.show()

        ret = qt_app.exec()
        if not is_attached:
            app.stop_background_services()
            remove_daemon_status(app.paths)
        return ret
    finally:
        if not is_attached:
            remove_daemon_status(app.paths)
            collector_guard.release()
        ui_guard.release()


if __name__ == "__main__":
    sys.exit(main())

