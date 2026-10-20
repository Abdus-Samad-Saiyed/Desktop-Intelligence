# Desktop Intelligence

A Windows-first, local-first desktop application that measures application usage, captures resource snapshots when relevant events occur, analyzes patterns with NumPy and Pandas, visualizes results via Matplotlib embedded in PySide6, and suggests or launches approved workflows.

---

## 1. Portable Python Bootstrapper Protection

This repository preserves the existing `setup.py` bootstrapper byte-for-byte unchanged.
- `setup.py` verifies virtual environment provisioning (`myenv`) and dependency installation.
- `main.py` safely calls `from setup import environment` and guards against missing virtual-environment interpreters and recursive relaunch loops.
- `requirements.txt` contains single, exact importable package names per line (no version constraints, extras, or comments) compatible with the bootstrapper's parser:
  - `matplotlib`
  - `numpy`
  - `pandas`
  - `psutil`
  - `PySide6`
  - `pytest`
  - `wmi`

---

## 2. Architecture & Resilience Improvements

Desktop Intelligence operates on an **event-driven architecture** rather than high-frequency polling:
- **Foreground transitions**: Captured via Windows `SetWinEventHook` (`EVENT_SYSTEM_FOREGROUND = 0x0003`).
- **Process starts (WMI resilience)**: Uses Windows WMI `Win32_ProcessStartTrace` with automatic fallback to user-accessible `Win32_Process` creation queries when running in non-elevated user contexts (`wmi.x_access_denied` / COM `0x80041003`). Health state is transparently reported via diagnostics.
- **System errors**: Captured from Windows Application Event Log (Event ID 1000).
- **Resource snapshots**: Triggered upon process start or foreground change.
- **Robust Qt Object Lifetimes**: Overview page safely updates dynamic recommendation widgets and prevents C++ `libshiboken` deletion errors across repeated UI data reloads.
- **Robust Visualizations**: Matplotlib charts guard against zero-hours and empty-data edge cases, completely eliminating singular coordinate transformation warnings.
- **Data storage**: Thread-safe, UTF-8 CSV files with explicit timezone-aware UTC timestamps (ISO 8601 ending in `Z`). Files are stored under the per-user data directory `%LOCALAPPDATA%/DesktopIntelligence/data`:
  - `activity_events.csv`: Event logs (`process_start`, `foreground_change`, etc.)
  - `activity_sessions.csv`: Bounded sessions with active duration, idle time, day of week, and time bucket.
  - `resource_samples.csv`: RSS bytes, process memory percentage, cumulative CPU time, system memory pressure.
  - `application_inventory.csv`: Installed software discovery from Windows Registry and Start Menu shortcuts.
  - `recommendations.csv`: Evidence-backed recommendations (`habit_launch`, `resource_hog`, `unused_application`).
  - `automation_log.csv`: Audit log for all scheduled automation attempts.

---

## 3. Configuration (`config.toml`)

All tunable behavior is centralized in `config.toml`:
- `[general]`: App name, config version, log level, timezone.
- `[paths]`: Custom `data_dir` and `log_dir` (defaults to `%LOCALAPPDATA%/DesktopIntelligence`).
- `[collection]`: Event toggles, idle timeout (default: 300s), idle check interval (default: 60s).
- `[retention]`: Data retention in days for events, sessions, and resource samples.
- `[patterns]`: Habit learning gate (minimum 14 observation days, 10 context occurrences, 80% launch frequency threshold).
- `[resources]`: High memory threshold (default: 15.0%), sustained observation count (default: 3).
- `[automation]`: Master toggle (default: `false`), rule approval requirement, 10s prompt timeout defaulting to `skip`.
- `[ui]`: Theme (`light`, `dark`, or `system`), `accent_color` (custom hex), tray icon, start minimized.

---

## 4. UI Dashboard & Modern Design System

The desktop application is built with PySide6 and embeds non-blocking Matplotlib figures styled according to the active theme:
- **Design Tokens & Theming**: Complete light and dark themes with system preference detection, glassmorphism card surfaces (`rgba(24, 31, 48, 0.72)` dark / `rgba(255, 255, 255, 0.78)` light), and 6 accent presets (Electric Violet `#8B5CF6`, Cyan Glow `#22D3EE`, Emerald `#34D399`, Royal Blue `#2563EB`, Amber `#FBBF24`, Rose `#FB7185`).
- **Overview**: High-level KPIs (Total Active Time, Top Application, Sessions, Data Freshness), top applications bar chart with responsive geometry tracking (`ThemedChartCanvas`), and pending recommendations with Approve/Dismiss actions.
- **Usage Analytics**: Application usage table with full-width stretching and side-by-side weekly distribution and daily trend charts.
- **System Health**: Resource consumption alerts with high-memory thresholds and Windows Application Reliability Events (crashes, hangs, and error diagnostics) filtered to exclude informational service heartbeats.
- **Applications**: Installed software inventory with observation status ("Active" vs "Not observed since monitoring began on <date>"), search filter, and discovery provenance.
- **Automation**: Master automation switch, consent policy notice, approved scheduled launch rules, and an auditable execution log.
- **Settings**: Live theme and accent controls, configuration persistence to `config.toml`, and file path diagnostics.
- **Multi-Source Collector Indicators**: Sidebar footer displays independent, honest statuses for Foreground Hook (`SetWinEventHook`), Process Start Trace (`WMI / Win32_Process`), and Diagnostics (`Windows Event Log`).

---

## 5. Usage Commands

Run the full application GUI:
```powershell
python main.py
```

Run in diagnostic mode (checks file paths, event sources, and record counts):
```powershell
python main.py --diagnostics
```

Run background collector daemon without GUI:
```powershell
python main.py --collector-only
```

Trigger an application inventory scan:
```powershell
python main.py --rescan-inventory
```

Generate full visual QA screenshots across all pages in both Dark and Light themes:
```powershell
.\myenv\Scripts\python scripts/capture_screenshots.py
```

Run the complete test suite:
```powershell
.\myenv\Scripts\pytest -v tests/unit tests/integration
```