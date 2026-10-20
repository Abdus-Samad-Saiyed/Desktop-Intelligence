"""Phase 4 tests: Data Truth (inventory counts from process_start only, resource exceedance vs observations, transient shell filtering, and dismissal cooldown)."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
import pandas as pd
import pytest

from desktop_intelligence.analytics.recommendations import generate_recommendations
from desktop_intelligence.analytics.resources import analyze_resource_hogs
from desktop_intelligence.app import DesktopIntelligenceApp
from desktop_intelligence.collectors.activity_manager import ActivityManager
from desktop_intelligence.collectors.base import FakeClock, RawEvent
from desktop_intelligence.collectors.foreground_events import is_transient_shell_window
from desktop_intelligence.config import AppConfig, ResourcesConfig
from desktop_intelligence.models import ActivityEvent, ActivitySession, RecommendationRecord, format_utc_iso
from desktop_intelligence.paths import resolve_paths
from desktop_intelligence.storage.csv_store import CsvStore


def test_inventory_launch_counts_only_from_process_start(tmp_path):
    """Verify inventory launch counts derive strictly from process_start events, never session counts."""
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    paths.ensure_directories()
    store = CsvStore(paths)
    config = AppConfig()

    app = DesktopIntelligenceApp(config=config, paths=paths, store=store)

    # 1. Write activity_events: AppA has 2 process_start events, AppB has 0
    t0 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
    evt1 = ActivityEvent(
        event_id="evt_1",
        event_ts_utc=format_utc_iso(t0),
        event_type="process_start",
        pid=100,
        process_name="AppA.exe",
        exe_path="C:\\Apps\\AppA.exe",
        event_source="wmi",
    )
    evt2 = ActivityEvent(
        event_id="evt_2",
        event_ts_utc=format_utc_iso(t0 + timedelta(minutes=10)),
        event_type="process_start",
        pid=101,
        process_name="AppA.exe",
        exe_path="C:\\Apps\\AppA.exe",
        event_source="wmi",
    )
    store.append_activity_event(evt1)
    store.append_activity_event(evt2)

    # 2. Write activity_sessions: AppA has 50 sessions (foreground switches), AppB has 30 sessions
    for i in range(50):
        s_a = ActivitySession(
            session_id=f"ses_a_{i}",
            process_name="AppA.exe",
            pid=100,
            start_ts_utc=format_utc_iso(t0 + timedelta(minutes=i)),
            end_ts_utc=format_utc_iso(t0 + timedelta(minutes=i, seconds=30)),
            duration_seconds=30.0,
            idle_seconds=0.0,
            local_date="2026-10-20",
            day_of_week="Tuesday",
            time_bucket="10:00",
        )
        store.append_activity_session(s_a)

    for i in range(30):
        s_b = ActivitySession(
            session_id=f"ses_b_{i}",
            process_name="AppB.exe",
            pid=200,
            start_ts_utc=format_utc_iso(t0 + timedelta(minutes=i)),
            end_ts_utc=format_utc_iso(t0 + timedelta(minutes=i, seconds=20)),
            duration_seconds=20.0,
            idle_seconds=0.0,
            local_date="2026-10-20",
            day_of_week="Tuesday",
            time_bucket="10:00",
        )
        store.append_activity_session(s_b)

    # Mock installed items discovery to return AppA and AppB
    from desktop_intelligence.models import InventoryItem
    fake_items = [
        InventoryItem(
            observed_ts_utc=format_utc_iso(t0),
            display_name="AppA",
            exe_path="C:\\Apps\\AppA.exe",
            inventory_source="registry",
            first_seen_ts_utc=format_utc_iso(t0),
            last_observed_launch_ts_utc=None,
            observed_launch_count=0,
        ),
        InventoryItem(
            observed_ts_utc=format_utc_iso(t0),
            display_name="AppB",
            exe_path="C:\\Apps\\AppB.exe",
            inventory_source="registry",
            first_seen_ts_utc=format_utc_iso(t0),
            last_observed_launch_ts_utc=None,
            observed_launch_count=0,
        ),
    ]

    class FakeScanner:
        def build_inventory(self, observed_launch_counts, last_launch_timestamps, existing_first_seen):
            res = []
            for item in fake_items:
                cnt = observed_launch_counts.get(item.display_name.lower(), 0) or observed_launch_counts.get(item.exe_path.lower(), 0)
                last_ts = last_launch_timestamps.get(item.display_name.lower()) or last_launch_timestamps.get(item.exe_path.lower())
                res.append(
                    InventoryItem(
                        observed_ts_utc=item.observed_ts_utc,
                        display_name=item.display_name,
                        exe_path=item.exe_path,
                        inventory_source=item.inventory_source,
                        first_seen_ts_utc=item.first_seen_ts_utc,
                        last_observed_launch_ts_utc=last_ts,
                        observed_launch_count=cnt,
                    )
                )
            return res

    app.inventory_scanner = FakeScanner()
    items = app.refresh_inventory()

    app_a = next(it for it in items if it.display_name == "AppA")
    app_b = next(it for it in items if it.display_name == "AppB")

    # AppA must have 2 launches (from process_start), NOT 50 (from sessions)
    assert app_a.observed_launch_count == 2
    # AppB must have 0 launches (0 process_start events), NOT 30
    assert app_b.observed_launch_count == 0


def test_resource_hogs_time_span_and_exceedance_separation():
    """Verify ResourceHogFinding separates total observed samples from threshold exceedances."""
    t0 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
    cfg = ResourcesConfig(high_memory_percent=50.0, sustained_observation_count=3)

    # 10 samples: 4 exceedances (>= 50%), 6 normal (< 50%)
    samples = []
    for i in range(10):
        mem = 65.0 if i in (1, 3, 5, 7) else 25.0
        samples.append({
            "process_name": "hog.exe",
            "process_memory_percent": mem,
            "rss_bytes": int(mem * 1024 * 1024),
            "sample_ts_utc": format_utc_iso(t0 + timedelta(minutes=i * 10)),
        })

    findings = analyze_resource_hogs(pd.DataFrame(samples), cfg)
    assert len(findings) == 1
    f = findings[0]

    assert f.is_hog is True
    assert f.exceedance_samples == 4
    assert f.total_samples == 10
    assert f.sustained_samples == 4
    assert f.observation_span_seconds == 9 * 600.0  # 90 minutes = 5400s
    assert "4 of 10 observations" in f.reason


def test_transient_shell_noise_filtering():
    """Verify transient shell window classes are classified correctly and do not disrupt user sessions."""
    # Classification tests
    assert is_transient_shell_window("explorer.exe", "Shell_TrayWnd") is True
    assert is_transient_shell_window("explorer.exe", "Shell_SecondaryTrayWnd") is True
    assert is_transient_shell_window("explorer.exe", "Progman") is True
    assert is_transient_shell_window("explorer.exe", "WorkerW") is True
    assert is_transient_shell_window("explorer.exe", "NotifyIconOverflowWindow") is True
    assert is_transient_shell_window("explorer.exe", "CabinetWClass") is False  # Real File Explorer!
    assert is_transient_shell_window("explorer.exe", "ExploreWClass") is False  # Real File Explorer!
    assert is_transient_shell_window("code.exe", "Chrome_WidgetWin_1") is False

    # ActivityManager session disruption test
    clock = FakeClock(start_utc=datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc))
    config = AppConfig()
    store = type("MockStore", (), {
        "paths": type("Paths", (), {"data_dir": Path("tmp_mock_data")})(),
        "append_activity_event": lambda self, e: None,
        "append_activity_session": lambda self, s: None,
        "append_resource_sample": lambda self, s: None,
    })()

    mgr = ActivityManager(config=config, store=store, clock=clock)

    # 1. User is working in Code.exe
    t1 = clock.now_utc()
    mgr._handle_foreground_transition(
        RawEvent(
            event_type="foreground_change",
            pid=123,
            process_name="Code.exe",
            exe_path="C:\\Apps\\Code.exe",
            timestamp_utc=t1,
            event_source="winevent",
            metadata={"window_class": "Chrome_WidgetWin_1", "is_transient_shell": False},
        )
    )
    assert mgr.active_session is not None
    assert mgr.active_session.process_name == "Code.exe"

    # 2. User clicks the taskbar (transient shell noise)
    clock.advance(5.0)
    t2 = clock.now_utc()
    mgr._handle_foreground_transition(
        RawEvent(
            event_type="foreground_change",
            pid=999,
            process_name="explorer.exe",
            exe_path="C:\\Windows\\explorer.exe",
            timestamp_utc=t2,
            event_source="winevent",
            metadata={"window_class": "Shell_TrayWnd", "is_transient_shell": True},
        )
    )
    # Session must remain Code.exe (NOT closed, NO explorer session)
    assert mgr.active_session is not None
    assert mgr.active_session.process_name == "Code.exe"
    assert mgr.active_session.last_active_utc == t2

    # 3. User opens a real File Explorer window (CabinetWClass)
    clock.advance(10.0)
    t3 = clock.now_utc()
    mgr._handle_foreground_transition(
        RawEvent(
            event_type="foreground_change",
            pid=999,
            process_name="explorer.exe",
            exe_path="C:\\Windows\\explorer.exe",
            timestamp_utc=t3,
            event_source="winevent",
            metadata={"window_class": "CabinetWClass", "is_transient_shell": False},
        )
    )
    # Now session legitimately transitions to explorer.exe
    assert mgr.active_session is not None
    assert mgr.active_session.process_name == "explorer.exe"


def test_recommendation_dismissal_rejection_cooldown(tmp_path):
    """Verify rejected/dismissed recommendations respect the 7-day cooldown period."""
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    paths.ensure_directories()
    store = CsvStore(paths)
    config = AppConfig()

    t0 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
    clock = FakeClock(start_utc=t0)

    # 1. Record a rejected recommendation in store
    rec_rejected = RecommendationRecord(
        recommendation_id="rec_rej_1",
        created_ts_utc=format_utc_iso(t0),
        category="resource_hog",
        subject="High memory consumption in bigapp.exe",
        evidence_json='{"max_memory_percent": 85.0}',
        confidence=0.85,
        status="rejected",  # Rejected status written by UI Dismiss button
    )
    store.append_recommendation(rec_rejected)

    # Samples that would trigger high memory for bigapp.exe
    samples_df = pd.DataFrame([
        {"process_name": "bigapp.exe", "process_memory_percent": 85.0, "rss_bytes": 1000000000}
        for _ in range(5)
    ])
    sessions_df = pd.DataFrame()

    # 2. Try to generate recommendations within cooldown (e.g. 2 days later)
    clock.advance(2 * 86400.0)
    new_recs = generate_recommendations(config, store, sessions_df, samples_df, [], clock=clock)
    # Must NOT recreate the rejected recommendation
    assert not any(r.subject == rec_rejected.subject for r in new_recs)

    # 3. Advance clock past 7 days (e.g. 8 days after dismissal)
    clock.set_time(t0 + timedelta(days=8))
    new_recs_after = generate_recommendations(config, store, sessions_df, samples_df, [], clock=clock)
    # Must be permitted after cooldown expiration
    assert any(r.subject == rec_rejected.subject for r in new_recs_after)
