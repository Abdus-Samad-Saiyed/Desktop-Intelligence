"""Data models, schemas, and UTC timestamp helpers for Desktop Intelligence."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any, Dict, List, Optional
import uuid


# ISO 8601 UTC regex for strict verification
ISO_UTC_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]00:00)$")


def now_utc() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def format_utc_iso(dt: datetime) -> str:
    """Format timezone-aware datetime to ISO 8601 UTC string ending in 'Z'.

    Rejects naive datetime objects to prevent ambiguous timestamps.
    """
    if dt is None:
        raise ValueError("Datetime cannot be None")
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"Naive datetime rejected: {dt!r}. Timestamps must be timezone-aware.")

    utc_dt = dt.astimezone(timezone.utc)
    # Format to millisecond precision with Z
    iso_str = utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return iso_str


def parse_utc_iso(ts_str: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp string into a timezone-aware UTC datetime."""
    if not ts_str or not isinstance(ts_str, str):
        raise ValueError(f"Invalid timestamp string: {ts_str!r}")

    cleaned = ts_str.strip()
    if not ISO_UTC_REGEX.match(cleaned):
        raise ValueError(f"Timestamp string must be in UTC ISO 8601 format (ending in 'Z' or '+00:00'): {ts_str!r}")

    if cleaned.endswith("Z"):
        dt = datetime.fromisoformat(cleaned[:-1] + "+00:00")
    else:
        dt = datetime.fromisoformat(cleaned)

    if dt.tzinfo is None:
        raise ValueError(f"Parsed naive datetime from timestamp string: {ts_str!r}")

    return dt.astimezone(timezone.utc)


def new_id(prefix: str = "") -> str:
    """Generate a unique ID string."""
    uid = uuid.uuid4().hex[:12]
    return f"{prefix}_{uid}" if prefix else uid


# Schema definitions with exact column ordering
SCHEMAS: Dict[str, List[str]] = {
    "activity_events": [
        "event_id", "event_ts_utc", "event_type", "pid", "process_name", "exe_path", "event_source"
    ],
    "activity_sessions": [
        "session_id", "process_name", "pid", "start_ts_utc", "end_ts_utc", "duration_seconds",
        "idle_seconds", "local_date", "day_of_week", "time_bucket"
    ],
    "resource_samples": [
        "sample_id", "sample_ts_utc", "trigger_event", "pid", "process_name", "rss_bytes",
        "process_memory_percent", "cpu_time_seconds", "system_memory_percent"
    ],
    "application_inventory": [
        "observed_ts_utc", "display_name", "exe_path", "inventory_source", "first_seen_ts_utc",
        "last_observed_launch_ts_utc", "observed_launch_count"
    ],
    "recommendations": [
        "recommendation_id", "created_ts_utc", "category", "subject", "evidence_json", "confidence", "status"
    ],
    "automation_log": [
        "log_id", "ts_utc", "rule_id", "action", "result", "reason"
    ],
}


@dataclass
class ActivityEvent:
    event_id: str
    event_ts_utc: str
    event_type: str  # "process_start", "foreground_change", "process_exit", etc.
    pid: int
    process_name: str
    exe_path: str
    event_source: str  # "wmi", "winevent", "poll_fallback", "fake"

    def to_row(self) -> List[str]:
        return [
            self.event_id,
            self.event_ts_utc,
            self.event_type,
            str(self.pid),
            self.process_name,
            self.exe_path,
            self.event_source,
        ]

    @classmethod
    def from_row(cls, row: Dict[str, str]) -> "ActivityEvent":
        return cls(
            event_id=row["event_id"],
            event_ts_utc=row["event_ts_utc"],
            event_type=row["event_type"],
            pid=int(row["pid"]) if row["pid"] else 0,
            process_name=row["process_name"],
            exe_path=row["exe_path"],
            event_source=row["event_source"],
        )


@dataclass
class ActivitySession:
    session_id: str
    process_name: str
    pid: int
    start_ts_utc: str
    end_ts_utc: str
    duration_seconds: float
    idle_seconds: float
    local_date: str
    day_of_week: str
    time_bucket: str

    def to_row(self) -> List[str]:
        return [
            self.session_id,
            self.process_name,
            str(self.pid),
            self.start_ts_utc,
            self.end_ts_utc,
            f"{self.duration_seconds:.3f}",
            f"{self.idle_seconds:.3f}",
            self.local_date,
            self.day_of_week,
            self.time_bucket,
        ]

    @classmethod
    def from_row(cls, row: Dict[str, str]) -> "ActivitySession":
        return cls(
            session_id=row["session_id"],
            process_name=row["process_name"],
            pid=int(row["pid"]) if row["pid"] else 0,
            start_ts_utc=row["start_ts_utc"],
            end_ts_utc=row["end_ts_utc"],
            duration_seconds=float(row["duration_seconds"]),
            idle_seconds=float(row["idle_seconds"]),
            local_date=row["local_date"],
            day_of_week=row["day_of_week"],
            time_bucket=row["time_bucket"],
        )


@dataclass
class ResourceSample:
    sample_id: str
    sample_ts_utc: str
    trigger_event: str  # "process_start", "foreground_change", "manual"
    pid: int
    process_name: str
    rss_bytes: Optional[int]
    process_memory_percent: Optional[float]
    cpu_time_seconds: Optional[float]
    system_memory_percent: Optional[float]

    def to_row(self) -> List[str]:
        return [
            self.sample_id,
            self.sample_ts_utc,
            self.trigger_event,
            str(self.pid),
            self.process_name,
            "" if self.rss_bytes is None else str(self.rss_bytes),
            "" if self.process_memory_percent is None else f"{self.process_memory_percent:.2f}",
            "" if self.cpu_time_seconds is None else f"{self.cpu_time_seconds:.3f}",
            "" if self.system_memory_percent is None else f"{self.system_memory_percent:.2f}",
        ]

    @classmethod
    def from_row(cls, row: Dict[str, str]) -> "ResourceSample":
        return cls(
            sample_id=row["sample_id"],
            sample_ts_utc=row["sample_ts_utc"],
            trigger_event=row["trigger_event"],
            pid=int(row["pid"]) if row["pid"] else 0,
            process_name=row["process_name"],
            rss_bytes=int(row["rss_bytes"]) if row.get("rss_bytes") else None,
            process_memory_percent=float(row["process_memory_percent"]) if row.get("process_memory_percent") else None,
            cpu_time_seconds=float(row["cpu_time_seconds"]) if row.get("cpu_time_seconds") else None,
            system_memory_percent=float(row["system_memory_percent"]) if row.get("system_memory_percent") else None,
        )


@dataclass
class InventoryItem:
    observed_ts_utc: str
    display_name: str
    exe_path: str
    inventory_source: str  # "registry", "start_menu", "observed_process"
    first_seen_ts_utc: str
    last_observed_launch_ts_utc: str
    observed_launch_count: int

    def to_row(self) -> List[str]:
        return [
            self.observed_ts_utc,
            self.display_name,
            self.exe_path,
            self.inventory_source,
            self.first_seen_ts_utc,
            self.last_observed_launch_ts_utc,
            str(self.observed_launch_count),
        ]

    @classmethod
    def from_row(cls, row: Dict[str, str]) -> "InventoryItem":
        return cls(
            observed_ts_utc=row["observed_ts_utc"],
            display_name=row["display_name"],
            exe_path=row["exe_path"],
            inventory_source=row["inventory_source"],
            first_seen_ts_utc=row["first_seen_ts_utc"],
            last_observed_launch_ts_utc=row["last_observed_launch_ts_utc"],
            observed_launch_count=int(row["observed_launch_count"]) if row.get("observed_launch_count") else 0,
        )


@dataclass
class RecommendationRecord:
    recommendation_id: str
    created_ts_utc: str
    category: str  # "habit_launch", "resource_hog", "unused_application"
    subject: str
    evidence_json: str
    confidence: float
    status: str  # "pending", "approved", "rejected", "applied"

    def to_row(self) -> List[str]:
        return [
            self.recommendation_id,
            self.created_ts_utc,
            self.category,
            self.subject,
            self.evidence_json,
            f"{self.confidence:.2f}",
            self.status,
        ]

    @classmethod
    def from_row(cls, row: Dict[str, str]) -> "RecommendationRecord":
        return cls(
            recommendation_id=row["recommendation_id"],
            created_ts_utc=row["created_ts_utc"],
            category=row["category"],
            subject=row["subject"],
            evidence_json=row["evidence_json"],
            confidence=float(row["confidence"]),
            status=row["status"],
        )


@dataclass
class AutomationLogRecord:
    log_id: str
    ts_utc: str
    rule_id: str
    action: str  # "prompt", "launch", "skip", "error"
    result: str  # "success", "skipped_duplicate", "timeout_skip", "rejected", "error"
    reason: str

    def to_row(self) -> List[str]:
        return [
            self.log_id,
            self.ts_utc,
            self.rule_id,
            self.action,
            self.result,
            self.reason,
        ]

    @classmethod
    def from_row(cls, row: Dict[str, str]) -> "AutomationLogRecord":
        return cls(
            log_id=row["log_id"],
            ts_utc=row["ts_utc"],
            rule_id=row["rule_id"],
            action=row["action"],
            result=row["result"],
            reason=row["reason"],
        )
