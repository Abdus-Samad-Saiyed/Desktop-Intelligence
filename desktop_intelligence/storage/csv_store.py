"""CSV storage engine with thread-safe append, schema validation, and integrity checks."""

import csv
from datetime import datetime, timezone, timedelta
import io
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

from desktop_intelligence.models import (
    SCHEMAS,
    ActivityEvent,
    ActivitySession,
    ResourceSample,
    InventoryItem,
    RecommendationRecord,
    AutomationLogRecord,
    parse_utc_iso,
    ISO_UTC_REGEX,
)
from desktop_intelligence.paths import ResolvedPaths


class StorageError(Exception):
    """Base exception for storage errors."""
    pass


class SchemaMismatchError(StorageError):
    """Raised when an existing CSV file's headers do not match the expected schema."""
    pass


class CorruptRowError(StorageError):
    """Raised when a CSV row has invalid column count or malformed fields."""
    pass


class CsvStore:
    """Thread-safe CSV store managing all application data records."""

    def __init__(self, paths: ResolvedPaths):
        self.paths = paths
        self._locks: Dict[str, threading.RLock] = {}
        self._global_lock = threading.RLock()

    def _get_lock(self, file_path: Path) -> threading.RLock:
        key = str(file_path.resolve())
        with self._global_lock:
            if key not in self._locks:
                self._locks[key] = threading.RLock()
            return self._locks[key]

    def initialize_file(self, schema_name: str, file_path: Path) -> None:
        """Ensure the CSV file exists and has the correct header.

        Raises SchemaMismatchError if the file exists and headers do not match.
        """
        expected_headers = SCHEMAS[schema_name]
        lock = self._get_lock(file_path)

        with lock:
            file_path.parent.mkdir(parents=True, exist_ok=True)

            if not file_path.exists() or file_path.stat().st_size == 0:
                with open(file_path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
                    writer.writerow(expected_headers)
                return

            # File exists and is non-empty; verify headers
            with open(file_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                try:
                    actual_headers = next(reader)
                except StopIteration:
                    actual_headers = []

            if actual_headers != expected_headers:
                raise SchemaMismatchError(
                    f"Schema mismatch in {file_path.name} for schema '{schema_name}'.\n"
                    f"Expected: {expected_headers}\n"
                    f"Actual:   {actual_headers}"
                )

    def append_row(self, schema_name: str, file_path: Path, row: List[str]) -> None:
        """Thread-safe append of a single row with schema and timestamp validation."""
        self.append_rows(schema_name, file_path, [row])

    def append_rows(self, schema_name: str, file_path: Path, rows: List[List[str]]) -> None:
        """Thread-safe append of multiple rows in one operation."""
        if not rows:
            return

        expected_headers = SCHEMAS[schema_name]
        expected_len = len(expected_headers)

        for row in rows:
            if len(row) != expected_len:
                raise CorruptRowError(
                    f"Row length {len(row)} does not match schema '{schema_name}' length {expected_len}: {row!r}"
                )

        lock = self._get_lock(file_path)
        with lock:
            self.initialize_file(schema_name, file_path)

            try:
                with open(file_path, "a", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
                    for row in rows:
                        writer.writerow(row)
            except OSError as exc:
                raise StorageError(f"Failed to append to {file_path}: {exc}") from exc

    def replace_all(self, schema_name: str, file_path: Path, rows: List[List[str]]) -> None:
        """Atomically replace entire contents of CSV file using a temporary file and os.replace."""
        expected_headers = SCHEMAS[schema_name]
        expected_len = len(expected_headers)
        for r in rows:
            if len(r) != expected_len:
                raise CorruptRowError(f"Row length {len(r)} does not match schema '{schema_name}' length {expected_len}: {r!r}")

        lock = self._get_lock(file_path)
        with lock:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = file_path.with_name(f"{file_path.name}.{os.getpid()}_{threading.get_ident()}.tmp")
            try:
                with open(tmp_path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
                    writer.writerow(expected_headers)
                    for row in rows:
                        writer.writerow(row)
                os.replace(tmp_path, file_path)
            except OSError as exc:
                raise StorageError(f"Failed to atomically write {file_path}: {exc}") from exc
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass

    def read_rows(self, schema_name: str, file_path: Path) -> List[Dict[str, str]]:
        """Read all rows from a CSV file into a list of dictionaries.

        Returns empty list if file doesn't exist or is empty.
        Raises SchemaMismatchError on header mismatch.
        """
        if not file_path.exists() or file_path.stat().st_size == 0:
            return []

        expected_headers = SCHEMAS[schema_name]
        lock = self._get_lock(file_path)

        with lock:
            with open(file_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                try:
                    headers = next(reader)
                except StopIteration:
                    return []

                if headers != expected_headers:
                    raise SchemaMismatchError(
                        f"Schema mismatch in {file_path.name}: expected {expected_headers}, got {headers}"
                    )

                results = []
                for row_idx, row in enumerate(reader, start=2):
                    if not row or (len(row) == 1 and not row[0].strip()):
                        continue  # skip accidental empty lines
                    if len(row) != len(headers):
                        # Skip or handle corrupt row
                        continue
                    results.append(dict(zip(headers, row)))

                return results

    def read_dataframe(self, schema_name: str, file_path: Path) -> pd.DataFrame:
        """Read CSV as a Pandas DataFrame with expected columns and normalized types."""
        expected_headers = SCHEMAS[schema_name]
        if not file_path.exists() or file_path.stat().st_size == 0:
            return pd.DataFrame(columns=expected_headers)

        lock = self._get_lock(file_path)
        with lock:
            try:
                df = pd.read_csv(file_path, encoding="utf-8", dtype=str, keep_default_na=False)
            except Exception as exc:
                raise StorageError(f"Failed to read DataFrame from {file_path}: {exc}") from exc

            if list(df.columns) != expected_headers:
                raise SchemaMismatchError(
                    f"Columns mismatch in {file_path.name}: expected {expected_headers}, got {list(df.columns)}"
                )
            return df

    # Typed convenience helpers
    def append_activity_event(self, event: ActivityEvent) -> None:
        self._validate_timestamp(event.event_ts_utc)
        self.append_row("activity_events", self.paths.activity_events_csv, event.to_row())

    def append_activity_session(self, session: ActivitySession) -> None:
        self._validate_timestamp(session.start_ts_utc)
        self._validate_timestamp(session.end_ts_utc)
        self.append_row("activity_sessions", self.paths.activity_sessions_csv, session.to_row())

    def append_resource_sample(self, sample: ResourceSample) -> None:
        self._validate_timestamp(sample.sample_ts_utc)
        self.append_row("resource_samples", self.paths.resource_samples_csv, sample.to_row())

    def append_inventory_item(self, item: InventoryItem) -> None:
        self._validate_timestamp(item.observed_ts_utc)
        self.append_row("application_inventory", self.paths.application_inventory_csv, item.to_row())

    def append_recommendation(self, rec: RecommendationRecord) -> None:
        self._validate_timestamp(rec.created_ts_utc)
        self.append_row("recommendations", self.paths.recommendations_csv, rec.to_row())

    def append_automation_log(self, log: AutomationLogRecord) -> None:
        self._validate_timestamp(log.ts_utc)
        self.append_row("automation_log", self.paths.automation_log_csv, log.to_row())

    def prune_retention(self, events_days: int, sessions_days: int, samples_days: int) -> Dict[str, int]:
        """Prune records older than configured retention days based on their UTC timestamp."""
        now = datetime.now(timezone.utc)
        pruned_counts = {"events": 0, "sessions": 0, "samples": 0}

        # 1. Activity Events
        if events_days > 0 and self.paths.activity_events_csv.exists():
            cutoff = now - timedelta(days=events_days)
            pruned_counts["events"] = self._prune_file(
                "activity_events", self.paths.activity_events_csv, "event_ts_utc", cutoff
            )

        # 2. Activity Sessions
        if sessions_days > 0 and self.paths.activity_sessions_csv.exists():
            cutoff = now - timedelta(days=sessions_days)
            pruned_counts["sessions"] = self._prune_file(
                "activity_sessions", self.paths.activity_sessions_csv, "end_ts_utc", cutoff
            )

        # 3. Resource Samples
        if samples_days > 0 and self.paths.resource_samples_csv.exists():
            cutoff = now - timedelta(days=samples_days)
            pruned_counts["samples"] = self._prune_file(
                "resource_samples", self.paths.resource_samples_csv, "sample_ts_utc", cutoff
            )

        return pruned_counts

    def _prune_file(self, schema_name: str, file_path: Path, ts_col: str, cutoff: datetime) -> int:
        lock = self._get_lock(file_path)
        with lock:
            rows = self.read_rows(schema_name, file_path)
            if not rows:
                return 0

            kept_rows = []
            removed_count = 0

            for r in rows:
                try:
                    row_dt = parse_utc_iso(r[ts_col])
                    if row_dt >= cutoff:
                        kept_rows.append([r[col] for col in SCHEMAS[schema_name]])
                    else:
                        removed_count += 1
                except Exception:
                    # In case of malformed timestamp, retain for safety
                    kept_rows.append([r[col] for col in SCHEMAS[schema_name]])

            if removed_count > 0:
                self.replace_all(schema_name, file_path, kept_rows)

            return removed_count

    def _validate_timestamp(self, ts_str: str) -> None:
        """Validate timestamp string is valid timezone-aware UTC ISO 8601."""
        if not ts_str or not isinstance(ts_str, str):
            raise ValueError(f"Invalid timestamp: {ts_str!r}")
        parse_utc_iso(ts_str)
