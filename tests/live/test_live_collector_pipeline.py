"""Live system test: Launch Notepad and assert process_start event is captured."""
import subprocess
import sys
import time
import pytest

from desktop_intelligence.collectors.base import RawEvent
from desktop_intelligence.collectors.windows_process_events import WindowsProcessStartListener


@pytest.mark.live
@pytest.mark.windows
def test_live_process_start_captures_notepad_within_5s():
    """Launch Notepad and assert WindowsProcessStartListener captures its launch."""
    if sys.platform != "win32":
        pytest.skip("Windows platform required for live WMI test")

    events = []
    listener = WindowsProcessStartListener(callback=lambda e: events.append(e))
    listener.start()

    # Allow listener thread to initialize
    time.sleep(1.0)

    proc = None
    try:
        proc = subprocess.Popen(["notepad.exe"])
        deadline = time.time() + 5.0
        captured = False
        while time.time() < deadline:
            time.sleep(0.2)
            matching = [e for e in events if "notepad" in e.process_name.lower()]
            if matching:
                captured = True
                break

        assert captured, f"Notepad launch not detected within 5s. Captured events: {events}"
    finally:
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:
                pass
        listener.stop()
