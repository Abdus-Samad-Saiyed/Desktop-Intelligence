"""Deterministic seed data generation for Demo Mode."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from typing import List

from desktop_intelligence.models import (
    ActivityEvent,
    ActivitySession,
    AutomationLogRecord,
    InventoryItem,
    RecommendationRecord,
    ResourceSample,
    format_utc_iso,
    new_id,
)
from desktop_intelligence.storage.csv_store import CsvStore


def seed_demo_data(store: CsvStore, base_time: datetime | None = None) -> None:
    """Populate store with a rich, deterministic set of simulated activity and metrics."""
    # Fixed base timestamp: Monday 2026-10-19 12:00:00 UTC
    if base_time is None:
        base_time = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Activity Events (process_start)
    events: List[ActivityEvent] = []
    # Seed launches for inventory launch count verification
    launch_specs = [
        ("Code.exe", "C:\\Users\\User\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe", 42),
        ("chrome.exe", "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", 28),
        ("slack.exe", "C:\\Users\\User\\AppData\\Local\\slack\\slack.exe", 15),
        ("WindowsTerminal.exe", "C:\\Program Files\\WindowsApps\\wt.exe", 12),
        ("photoshop.exe", "C:\\Program Files\\Adobe\\Photoshop\\photoshop.exe", 6),
        ("docker.exe", "C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe", 8),
        ("calc.exe", "C:\\Windows\\System32\\calc.exe", 5),
    ]

    for p_name, exe, count in launch_specs:
        for i in range(count):
            t_evt = base_time - timedelta(days=(count - i) % 7, hours=i % 8, minutes=i * 3)
            events.append(
                ActivityEvent(
                    event_id=new_id("evt"),
                    event_ts_utc=format_utc_iso(t_evt),
                    event_type="process_start",
                    pid=1000 + i,
                    process_name=p_name,
                    exe_path=exe,
                    event_source="wmi",
                )
            )

    store.replace_all("activity_events", store.paths.activity_events_csv, [e.to_row() for e in events])

    # 2. Activity Sessions (exercising duration formats and habit patterns)
    # Total active times:
    # Code.exe: ~3 h 45 min (13500 s)
    # chrome.exe: ~1 h 15 min (4500 s)
    # slack.exe: ~42 min (2520 s)
    # WindowsTerminal.exe: ~18 min (1080 s)
    # calc.exe: ~36 s (36 s)
    sessions: List[ActivitySession] = []

    # Monday morning habit launches for Code.exe (4 Mondays at 09:00)
    for m in range(4):
        mon_dt = base_time - timedelta(days=m * 7)
        mon_start = mon_dt.replace(hour=9, minute=0, second=0)
        sessions.append(
            ActivitySession(
                session_id=new_id("ses"),
                process_name="Code.exe",
                pid=2000 + m,
                start_ts_utc=format_utc_iso(mon_start),
                end_ts_utc=format_utc_iso(mon_start + timedelta(minutes=45)),
                duration_seconds=2700.0,
                idle_seconds=0.0,
                local_date=mon_start.strftime("%Y-%m-%d"),
                day_of_week="Monday",
                time_bucket="09:00",
            )
        )

    # Additional Code.exe sessions
    for d, dow in enumerate(["Tuesday", "Wednesday", "Thursday", "Friday"]):
        d_start = base_time - timedelta(days=d + 1)
        d_start = d_start.replace(hour=14, minute=0, second=0)
        sessions.append(
            ActivitySession(
                session_id=new_id("ses"),
                process_name="Code.exe",
                pid=2100 + d,
                start_ts_utc=format_utc_iso(d_start),
                end_ts_utc=format_utc_iso(d_start + timedelta(minutes=40)),
                duration_seconds=2400.0,
                idle_seconds=0.0,
                local_date=d_start.strftime("%Y-%m-%d"),
                day_of_week=dow,
                time_bucket="14:00",
            )
        )

    # Chrome.exe sessions (Total 4500 s = 1 h 15 min)
    chrome_start = base_time.replace(hour=10, minute=30, second=0)
    sessions.append(
        ActivitySession(
            session_id=new_id("ses"),
            process_name="chrome.exe",
            pid=2200,
            start_ts_utc=format_utc_iso(chrome_start),
            end_ts_utc=format_utc_iso(chrome_start + timedelta(minutes=45)),
            duration_seconds=2700.0,
            idle_seconds=120.0,
            local_date=chrome_start.strftime("%Y-%m-%d"),
            day_of_week="Monday",
            time_bucket="10:00",
        )
    )
    chrome_start2 = (base_time - timedelta(days=1)).replace(hour=11, minute=0, second=0)
    sessions.append(
        ActivitySession(
            session_id=new_id("ses"),
            process_name="chrome.exe",
            pid=2201,
            start_ts_utc=format_utc_iso(chrome_start2),
            end_ts_utc=format_utc_iso(chrome_start2 + timedelta(minutes=30)),
            duration_seconds=1800.0,
            idle_seconds=60.0,
            local_date=chrome_start2.strftime("%Y-%m-%d"),
            day_of_week="Sunday",
            time_bucket="11:00",
        )
    )

    # Slack: 42 min = 2520 s
    slack_start = base_time.replace(hour=13, minute=0, second=0)
    sessions.append(
        ActivitySession(
            session_id=new_id("ses"),
            process_name="slack.exe",
            pid=2300,
            start_ts_utc=format_utc_iso(slack_start),
            end_ts_utc=format_utc_iso(slack_start + timedelta(minutes=42)),
            duration_seconds=2520.0,
            idle_seconds=0.0,
            local_date=slack_start.strftime("%Y-%m-%d"),
            day_of_week="Monday",
            time_bucket="13:00",
        )
    )

    # Terminal: 18 min = 1080 s
    term_start = base_time.replace(hour=15, minute=0, second=0)
    sessions.append(
        ActivitySession(
            session_id=new_id("ses"),
            process_name="WindowsTerminal.exe",
            pid=2400,
            start_ts_utc=format_utc_iso(term_start),
            end_ts_utc=format_utc_iso(term_start + timedelta(minutes=18)),
            duration_seconds=1080.0,
            idle_seconds=0.0,
            local_date=term_start.strftime("%Y-%m-%d"),
            day_of_week="Monday",
            time_bucket="15:00",
        )
    )

    # Calculator: 36 s
    calc_start = base_time.replace(hour=16, minute=0, second=0)
    sessions.append(
        ActivitySession(
            session_id=new_id("ses"),
            process_name="calc.exe",
            pid=2500,
            start_ts_utc=format_utc_iso(calc_start),
            end_ts_utc=format_utc_iso(calc_start + timedelta(seconds=36)),
            duration_seconds=36.0,
            idle_seconds=0.0,
            local_date=calc_start.strftime("%Y-%m-%d"),
            day_of_week="Monday",
            time_bucket="16:00",
        )
    )

    store.replace_all("activity_sessions", store.paths.activity_sessions_csv, [s.to_row() for s in sessions])

    # 3. Resource Samples (high memory processes)
    samples: List[ResourceSample] = []
    # photoshop: 6 observations, 4 exceedances (peak 82.5%, RSS 3.2GB)
    for i in range(6):
        mem = 82.5 if i == 0 else (76.0 if i < 4 else 45.0)
        t_samp = base_time - timedelta(hours=i)
        samples.append(
            ResourceSample(
                sample_id=new_id("samp"),
                sample_ts_utc=format_utc_iso(t_samp),
                trigger_event="foreground_change",
                pid=3000,
                process_name="photoshop.exe",
                rss_bytes=int(mem * 1024 * 1024 * 38),
                process_memory_percent=mem,
                cpu_time_seconds=120.0 + i * 30.0,
                system_memory_percent=78.0,
            )
        )

    # Code.exe: normal consumption (20% RAM)
    for i in range(8):
        t_samp = base_time - timedelta(hours=i * 2)
        samples.append(
            ResourceSample(
                sample_id=new_id("samp"),
                sample_ts_utc=format_utc_iso(t_samp),
                trigger_event="foreground_change",
                pid=2000,
                process_name="Code.exe",
                rss_bytes=1024 * 1024 * 650,
                process_memory_percent=19.5,
                cpu_time_seconds=250.0 + i * 15.0,
                system_memory_percent=55.0,
            )
        )

    store.replace_all("resource_samples", store.paths.resource_samples_csv, [s.to_row() for s in samples])

    # 4. Application Inventory (10+ applications, launch counts, first seen)
    inventory = [
        InventoryItem(
            observed_ts_utc=format_utc_iso(base_time),
            display_name="Visual Studio Code",
            exe_path="C:\\Users\\User\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe",
            inventory_source="registry;start_menu",
            first_seen_ts_utc=format_utc_iso(base_time - timedelta(days=30)),
            last_observed_launch_ts_utc=format_utc_iso(base_time - timedelta(hours=2)),
            observed_launch_count=42,
        ),
        InventoryItem(
            observed_ts_utc=format_utc_iso(base_time),
            display_name="Google Chrome",
            exe_path="C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            inventory_source="registry;start_menu",
            first_seen_ts_utc=format_utc_iso(base_time - timedelta(days=30)),
            last_observed_launch_ts_utc=format_utc_iso(base_time - timedelta(hours=1)),
            observed_launch_count=28,
        ),
        InventoryItem(
            observed_ts_utc=format_utc_iso(base_time),
            display_name="Slack",
            exe_path="C:\\Users\\User\\AppData\\Local\\slack\\slack.exe",
            inventory_source="start_menu",
            first_seen_ts_utc=format_utc_iso(base_time - timedelta(days=25)),
            last_observed_launch_ts_utc=format_utc_iso(base_time - timedelta(hours=3)),
            observed_launch_count=15,
        ),
        InventoryItem(
            observed_ts_utc=format_utc_iso(base_time),
            display_name="Windows Terminal",
            exe_path="C:\\Program Files\\WindowsApps\\wt.exe",
            inventory_source="start_menu",
            first_seen_ts_utc=format_utc_iso(base_time - timedelta(days=20)),
            last_observed_launch_ts_utc=format_utc_iso(base_time - timedelta(hours=4)),
            observed_launch_count=12,
        ),
        InventoryItem(
            observed_ts_utc=format_utc_iso(base_time),
            display_name="Docker Desktop",
            exe_path="C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe",
            inventory_source="registry",
            first_seen_ts_utc=format_utc_iso(base_time - timedelta(days=15)),
            last_observed_launch_ts_utc=format_utc_iso(base_time - timedelta(days=1)),
            observed_launch_count=8,
        ),
        InventoryItem(
            observed_ts_utc=format_utc_iso(base_time),
            display_name="Adobe Photoshop 2026",
            exe_path="C:\\Program Files\\Adobe\\Photoshop\\photoshop.exe",
            inventory_source="registry",
            first_seen_ts_utc=format_utc_iso(base_time - timedelta(days=14)),
            last_observed_launch_ts_utc=format_utc_iso(base_time - timedelta(hours=5)),
            observed_launch_count=6,
        ),
        InventoryItem(
            observed_ts_utc=format_utc_iso(base_time),
            display_name="Calculator",
            exe_path="C:\\Windows\\System32\\calc.exe",
            inventory_source="start_menu",
            first_seen_ts_utc=format_utc_iso(base_time - timedelta(days=30)),
            last_observed_launch_ts_utc=format_utc_iso(base_time - timedelta(hours=6)),
            observed_launch_count=5,
        ),
        InventoryItem(
            observed_ts_utc=format_utc_iso(base_time),
            display_name="Git",
            exe_path="C:\\Program Files\\Git\\cmd\\git.exe",
            inventory_source="registry",
            first_seen_ts_utc=format_utc_iso(base_time - timedelta(days=30)),
            last_observed_launch_ts_utc=None,
            observed_launch_count=0,
        ),
        InventoryItem(
            observed_ts_utc=format_utc_iso(base_time),
            display_name="Notepad++",
            exe_path="C:\\Program Files\\Notepad++\\notepad++.exe",
            inventory_source="registry;start_menu",
            first_seen_ts_utc=format_utc_iso(base_time - timedelta(days=30)),
            last_observed_launch_ts_utc=None,
            observed_launch_count=0,
        ),
        InventoryItem(
            observed_ts_utc=format_utc_iso(base_time),
            display_name="7-Zip File Manager",
            exe_path="C:\\Program Files\\7-Zip\\7zFM.exe",
            inventory_source="registry",
            first_seen_ts_utc=format_utc_iso(base_time - timedelta(days=30)),
            last_observed_launch_ts_utc=None,
            observed_launch_count=0,
        ),
    ]
    store.replace_all("application_inventory", store.paths.application_inventory_csv, [it.to_row() for it in inventory])

    # 5. Smart Recommendations
    recs = [
        RecommendationRecord(
            recommendation_id="rec_demo_habit_1",
            created_ts_utc=format_utc_iso(base_time),
            category="habit_launch",
            subject="Launch Visual Studio Code on Monday at 09:00",
            evidence_json=json.dumps({
                "app_name": "Visual Studio Code",
                "day_of_week": "Monday",
                "time_bucket": "09:00",
                "launches_in_context": 4,
                "context_occurrences": 4,
                "frequency_percent": 100,
            }),
            confidence=0.88,
            status="pending",
        ),
        RecommendationRecord(
            recommendation_id="rec_demo_hog_1",
            created_ts_utc=format_utc_iso(base_time),
            category="resource_hog",
            subject="High memory consumption in photoshop.exe",
            evidence_json=json.dumps({
                "process_name": "photoshop.exe",
                "max_memory_percent": 82.5,
                "avg_memory_percent": 68.4,
                "sustained_samples": 4,
                "reason": "Exceeded 70.0% threshold in 4 of 6 observations.",
            }),
            confidence=0.82,
            status="pending",
        ),
        RecommendationRecord(
            recommendation_id="rec_demo_unused_1",
            created_ts_utc=format_utc_iso(base_time),
            category="unused_application",
            subject="Application not observed in use: Notepad++",
            evidence_json=json.dumps({
                "display_name": "Notepad++",
                "observation_days": 30,
            }),
            confidence=0.75,
            status="pending",
        ),
    ]
    store.replace_all("recommendations", store.paths.recommendations_csv, [r.to_row() for r in recs])

    # 6. Automation Log (1 success, 1 skipped)
    logs = [
        AutomationLogRecord(
            log_id="log_demo_1",
            ts_utc=format_utc_iso(base_time - timedelta(days=7)),
            rule_id="rec_demo_habit_1",
            action="launch",
            result="success",
            reason="Automated launch executed after user confirmation.",
        ),
        AutomationLogRecord(
            log_id="log_demo_2",
            ts_utc=format_utc_iso(base_time - timedelta(days=14)),
            rule_id="rec_demo_habit_1",
            action="launch",
            result="skipped",
            reason="User prompted but consent timed out.",
        ),
    ]
    store.replace_all("automation_log", store.paths.automation_log_csv, [l.to_row() for l in logs])
