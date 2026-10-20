"""Human-readable durations shared by UI text, tables and Matplotlib axes. No Qt imports."""
from __future__ import annotations

import math
from typing import Optional

UNAVAILABLE = "\u2014"  # em dash: a missing value must never be shown as 0


def format_duration(seconds: Optional[float], *, use_days: bool = False) -> str:
    """45 s, 42 min, 1 h 05 min, 2 h, and with use_days 2 d 4 h.

    From 60 s upward the value is rounded to whole minutes first and then split,
    so 3599.6 s gives 1 h and never 60 min.
    """
    if seconds is None:
        return UNAVAILABLE
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return UNAVAILABLE
    if math.isnan(s) or math.isinf(s):
        return UNAVAILABLE
    s = max(0.0, s)
    if s < 59.5:
        return f"{int(math.floor(s + 0.5))} s"
    total_min = int(math.floor(s / 60.0 + 0.5))
    if total_min < 60:
        return f"{total_min} min"
    hours, minutes = divmod(total_min, 60)
    if use_days and hours >= 48:
        days, hours = divmod(hours, 24)
        return f"{days} d {hours} h" if hours else f"{days} d"
    if minutes == 0:
        return f"{hours} h"
    return f"{hours} h {minutes:02d} min"


def format_duration_hours(hours: Optional[float], **kw) -> str:
    """Format duration in decimal hours into human-readable duration."""
    try:
        return format_duration(float(hours) * 3600.0, **kw)
    except (TypeError, ValueError):
        return UNAVAILABLE


def nice_time_step_hours(max_hours: float) -> float:
    """Tick step in hours that lands on whole minutes or hours for the visible range."""
    span_min = max(max_hours, 1e-9) * 60.0
    for step in (1, 5, 10, 15, 30, 60, 120, 180, 360, 720, 1440):
        if span_min / step <= 6:
            return step / 60.0
    return 24.0


def format_tick_hours(value: float, _pos=None) -> str:
    """Format numeric axis tick values in hours into friendly duration labels."""
    if abs(value) < 1e-9:
        return "0"
    if value < 0:
        return ""  # off-range tick: draw nothing instead of a fake 0 s
    return format_duration(value * 3600.0)
