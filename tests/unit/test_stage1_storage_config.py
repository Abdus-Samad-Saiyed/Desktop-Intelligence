"""Stage 1 tests: Configuration validation, paths, schema definitions, and thread-safe CSV storage."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import pytest

from desktop_intelligence.config import (
    AppConfig,
    ConfigValidationError,
    load_config,
    validate_config_dict,
)
from desktop_intelligence.models import (
    SCHEMAS,
    ActivityEvent,
    ActivitySession,
    ResourceSample,
    InventoryItem,
    RecommendationRecord,
    AutomationLogRecord,
    format_utc_iso,
    parse_utc_iso,
    now_utc,
    new_id,
)
from desktop_intelligence.paths import ResolvedPaths, resolve_paths
from desktop_intelligence.storage.csv_store import (
    CsvStore,
    StorageError,
    SchemaMismatchError,
    CorruptRowError,
)


def test_default_config_loads_all_fields():
    config_file = Path(__file__).resolve().parents[2] / "config.toml"
    assert config_file.exists(), "config.toml must exist in repo root"

    cfg = load_config(config_file)
    assert cfg.general.app_name == "Desktop Intelligence"
    assert cfg.general.config_version == 1
    assert cfg.general.log_level == "INFO"
    assert cfg.general.timezone == "local"

    assert cfg.collection.enable_process_start_events is True
    assert cfg.collection.enable_foreground_events is True
    assert cfg.collection.idle_timeout_seconds == 300
    assert cfg.collection.idle_check_interval_seconds == 60
    assert cfg.collection.collect_window_titles is False

    assert cfg.retention.events_days == 180
    assert cfg.retention.sessions_days == 365
    assert cfg.retention.resource_samples_days == 90

    assert cfg.patterns.minimum_observation_days == 14
    assert cfg.patterns.minimum_context_occurrences == 10
    assert cfg.patterns.launch_frequency_threshold == 0.80
    assert cfg.patterns.time_bucket_minutes == 60

    assert cfg.resources.high_memory_percent == 15.0
    assert cfg.resources.high_system_memory_percent == 85.0
    assert cfg.resources.high_cpu_percent == 80.0

    assert cfg.automation.enabled is False
    assert cfg.automation.require_rule_approval is True
    assert cfg.automation.prompt_timeout_seconds == 10
    assert cfg.automation.no_response_action == "skip"

    assert cfg.ui.theme == "light"
    assert cfg.ui.accent_color == "#635BFF"
    assert cfg.llm.enabled is False


def test_missing_config_behavior(tmp_path):
    missing_file = tmp_path / "nonexistent.toml"
    # Fallback enabled
    default_cfg = load_config(missing_file, fallback_on_missing=True)
    assert default_cfg.general.app_name == "Desktop Intelligence"

    # Fallback disabled
    with pytest.raises(FileNotFoundError):
        load_config(missing_file, fallback_on_missing=False)


def test_malformed_toml_syntax(tmp_path):
    bad_toml = tmp_path / "bad.toml"
    bad_toml.write_text("[general\nunclosed = true", encoding="utf-8")
    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(bad_toml)
    assert "Malformed TOML" in str(exc_info.value)


@pytest.mark.parametrize(
    "patch,expected_err",
    [
        ({"general": {"log_level": "INVALID_LEVEL"}}, "log_level unknown"),
        ({"general": {"config_version": 0}}, "config_version must be integer >= 1"),
        ({"general": {"timezone": "Jupiter/Red_Spot"}}, "timezone is invalid"),
        ({"collection": {"idle_timeout_seconds": -10}}, "idle_timeout_seconds must be positive integer"),
        ({"collection": {"idle_timeout_seconds": "300"}}, "idle_timeout_seconds must be positive integer"),
        ({"retention": {"events_days": 0}}, "events_days must be positive integer"),
        ({"patterns": {"minimum_observation_days": 0}}, "minimum_observation_days must be integer >= 1"),
        ({"patterns": {"launch_frequency_threshold": 1.5}}, "launch_frequency_threshold must be in range"),
        ({"patterns": {"launch_frequency_threshold": 0.0}}, "launch_frequency_threshold must be in range"),
        ({"patterns": {"time_bucket_minutes": 2000}}, "time_bucket_minutes must be between 1 and 1440"),
        ({"patterns": {"eligible_day_types": ["holiday"]}}, "eligible_day_types must be non-empty subset"),
        ({"resources": {"high_memory_percent": 110.0}}, "high_memory_percent must be between 0.0 and 100.0"),
        ({"resources": {"high_memory_percent": -5.0}}, "high_memory_percent must be between 0.0 and 100.0"),
        ({"automation": {"no_response_action": "delete_all"}}, "no_response_action must be 'skip' or 'launch'"),
        ({"automation": {"prompt_timeout_seconds": 0}}, "prompt_timeout_seconds must be positive integer"),
        ({"ui": {"theme": "neon"}}, "theme must be one of"),
        ({"ui": {"accent_color": "not_a_color"}}, "accent_color must be a valid hex color"),
    ],
)
def test_config_validation_rules(patch, expected_err):
    with pytest.raises(ConfigValidationError) as exc:
        validate_config_dict(patch)
    assert expected_err in str(exc.value)


def test_utc_timestamp_handling():
    # Naive timestamp must be rejected
    naive_dt = datetime(2026, 10, 18, 14, 30, 0)
    with pytest.raises(ValueError) as exc:
        format_utc_iso(naive_dt)
    assert "Naive datetime rejected" in str(exc.value)

    # Timezone aware
    aware_dt = datetime(2026, 10, 18, 14, 30, 0, 123456, tzinfo=timezone.utc)
    iso_str = format_utc_iso(aware_dt)
    assert iso_str.endswith("Z")
    assert iso_str == "2026-10-18T14:30:00.123Z"

    parsed = parse_utc_iso(iso_str)
    assert parsed.tzinfo == timezone.utc
    assert parsed.year == 2026
    assert parsed.month == 10
    assert parsed.day == 18
    assert parsed.hour == 14
    assert parsed.minute == 30
    assert parsed.second == 0


def test_csv_store_initialization_and_single_header(tmp_path):
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    store = CsvStore(paths)

    now_ts = format_utc_iso(now_utc())
    evt1 = ActivityEvent(
        event_id="evt_1",
        event_ts_utc=now_ts,
        event_type="process_start",
        pid=1234,
        process_name="code.exe",
        exe_path="C:\\Program Files\\VSCode\\code.exe",
        event_source="wmi",
    )
    store.append_activity_event(evt1)

    # Verify header line + 1 data line
    content = paths.activity_events_csv.read_text(encoding="utf-8").splitlines()
    assert len(content) == 2
    assert content[0] == ",".join(SCHEMAS["activity_events"])

    # Second append: header must not be duplicated
    evt2 = ActivityEvent(
        event_id="evt_2",
        event_ts_utc=now_ts,
        event_type="foreground_change",
        pid=1234,
        process_name="code.exe",
        exe_path="C:\\Program Files\\VSCode\\code.exe",
        event_source="winevent",
    )
    store.append_activity_event(evt2)

    content2 = paths.activity_events_csv.read_text(encoding="utf-8").splitlines()
    assert len(content2) == 3
    assert content2[0] == ",".join(SCHEMAS["activity_events"])
    assert "evt_1" in content2[1]
    assert "evt_2" in content2[2]


def test_csv_special_characters_and_json_roundtrip(tmp_path):
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    store = CsvStore(paths)

    evidence_dict = {
        "launch_rate": 0.85,
        "sample_count": 12,
        "context": "weekday 09:00",
        "notes": 'Quotes "inside", commas, and\nnewline characters',
        "unicode": "測試 🚀 éàç",
    }
    evidence_json = json.dumps(evidence_dict)
    ts = format_utc_iso(now_utc())

    rec = RecommendationRecord(
        recommendation_id="rec_999",
        created_ts_utc=ts,
        category="habit_launch",
        subject='App with "Quotes" and, Commas',
        evidence_json=evidence_json,
        confidence=0.88,
        status="pending",
    )
    store.append_recommendation(rec)

    rows = store.read_rows("recommendations", paths.recommendations_csv)
    assert len(rows) == 1
    loaded = rows[0]
    assert loaded["recommendation_id"] == "rec_999"
    assert loaded["subject"] == 'App with "Quotes" and, Commas'
    assert loaded["confidence"] == "0.88"
    assert loaded["status"] == "pending"

    # Decode JSON and verify exact content round-tripped
    loaded_evidence = json.loads(loaded["evidence_json"])
    assert loaded_evidence == evidence_dict

    # Check Pandas read
    df = store.read_dataframe("recommendations", paths.recommendations_csv)
    assert len(df) == 1
    assert df.iloc[0]["recommendation_id"] == "rec_999"
    assert json.loads(df.iloc[0]["evidence_json"]) == evidence_dict


def test_schema_mismatch_error(tmp_path):
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    paths.ensure_directories()
    # Write a CSV file with bogus headers
    paths.activity_events_csv.write_text("col_a,col_b,col_c\n1,2,3\n", encoding="utf-8")

    store = CsvStore(paths)
    with pytest.raises(SchemaMismatchError) as exc_info:
        store.read_rows("activity_events", paths.activity_events_csv)
    assert "Schema mismatch" in str(exc_info.value)

    with pytest.raises(SchemaMismatchError):
        store.append_row("activity_events", paths.activity_events_csv, ["a"] * 7)


def test_corrupt_row_error(tmp_path):
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    store = CsvStore(paths)

    # Activity events has 7 columns, give 5
    with pytest.raises(CorruptRowError) as exc:
        store.append_row("activity_events", paths.activity_events_csv, ["1", "2", "3", "4", "5"])
    assert "does not match schema" in str(exc.value)


def test_concurrent_appends(tmp_path):
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    store = CsvStore(paths)

    total_threads = 8
    rows_per_thread = 25
    expected_total_rows = total_threads * rows_per_thread

    def worker(worker_id: int):
        for i in range(rows_per_thread):
            ts = format_utc_iso(now_utc())
            evt = ActivityEvent(
                event_id=f"evt_{worker_id}_{i}",
                event_ts_utc=ts,
                event_type="process_start",
                pid=1000 + worker_id,
                process_name=f"proc_{worker_id}.exe",
                exe_path=f"C:\\Path\\proc_{worker_id}.exe",
                event_source="fake",
            )
            store.append_activity_event(evt)

    with ThreadPoolExecutor(max_workers=total_threads) as executor:
        futures = [executor.submit(worker, w) for w in range(total_threads)]
        for f in futures:
            f.result()

    rows = store.read_rows("activity_events", paths.activity_events_csv)
    assert len(rows) == expected_total_rows

    df = store.read_dataframe("activity_events", paths.activity_events_csv)
    assert len(df) == expected_total_rows
    assert len(set(df["event_id"])) == expected_total_rows


def test_retention_pruning(tmp_path):
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    store = CsvStore(paths)

    now = datetime.now(timezone.utc)
    old_ts = format_utc_iso(now - timedelta(days=200))
    fresh_ts = format_utc_iso(now - timedelta(days=10))

    # Append one old event and one fresh event
    store.append_activity_event(ActivityEvent(
        event_id="old_evt",
        event_ts_utc=old_ts,
        event_type="process_start",
        pid=100,
        process_name="old.exe",
        exe_path="C:\\old.exe",
        event_source="test"
    ))
    store.append_activity_event(ActivityEvent(
        event_id="fresh_evt",
        event_ts_utc=fresh_ts,
        event_type="process_start",
        pid=200,
        process_name="fresh.exe",
        exe_path="C:\\fresh.exe",
        event_source="test"
    ))

    # Prune with 180 days limit
    pruned = store.prune_retention(events_days=180, sessions_days=365, samples_days=90)
    assert pruned["events"] == 1

    remaining = store.read_rows("activity_events", paths.activity_events_csv)
    assert len(remaining) == 1
    assert remaining[0]["event_id"] == "fresh_evt"
