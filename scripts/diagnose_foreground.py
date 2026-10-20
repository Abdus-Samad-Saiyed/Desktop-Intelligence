"""Diagnostic utility to inspect foreground window events, HWNDs, window classes, and classification."""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

if sys.platform != "win32":
    print("Error: diagnose_foreground.py must be run on Windows.")
    sys.exit(1)

from desktop_intelligence.collectors.foreground_events import (
    WindowsForegroundHook,
    get_window_class,
    is_transient_shell_window,
    resolve_uwp_window,
)
from desktop_intelligence.collectors.base import RawEvent


def main():
    parser = argparse.ArgumentParser(description="Diagnose Windows foreground window transitions and classes.")
    parser.add_argument("--duration", type=int, default=15, help="Observation duration in seconds (default: 15s)")
    args = parser.parse_args()

    print(f"[*] Starting foreground event diagnosis for {args.duration}s...")
    print(f"[*] Switch between windows, click taskbar, desktop, and File Explorer to observe classifications.\n")
    print(f"{'TIMESTAMP':<12} {'PID':<8} {'PROCESS':<25} {'WINDOW CLASS':<30} {'CLASSIFICATION'}")
    print("-" * 95)

    count = 0

    def on_event(event: RawEvent):
        nonlocal count
        count += 1
        ts_str = event.timestamp_utc.strftime("%H:%M:%S.%f")[:12]
        meta = event.metadata or {}
        win_class = meta.get("window_class", "unknown")
        is_transient = meta.get("is_transient_shell", False)
        classification = "TRANSIENT_SHELL (Ignored)" if is_transient else "APPLICATION_SESSION"
        print(f"{ts_str:<12} {event.pid:<8} {event.process_name:<25} {win_class:<30} {classification}")

    hook = WindowsForegroundHook(callback=on_event)
    hook.start()

    try:
        time.sleep(args.duration)
    except KeyboardInterrupt:
        print("\n[*] Stopped by user.")
    finally:
        hook.stop()

    print("-" * 95)
    print(f"[*] Diagnosis complete. Captured {count} foreground events.")


if __name__ == "__main__":
    main()
