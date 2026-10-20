"""Configuration loader and validator for Desktop Intelligence."""

from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
import sys
import tomllib
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigValidationError(ValueError):
    """Raised when configuration values are invalid or malformed."""
    pass


@dataclass
class GeneralConfig:
    app_name: str = "Desktop Intelligence"
    config_version: int = 1
    log_level: str = "INFO"
    timezone: str = "local"


@dataclass
class PathsConfig:
    data_dir: str = ""
    log_dir: str = ""


@dataclass
class CollectionConfig:
    enable_process_start_events: bool = True
    enable_foreground_events: bool = True
    enable_application_inventory: bool = True
    enable_system_error_events: bool = True
    idle_timeout_seconds: int = 300
    idle_check_interval_seconds: int = 60
    resource_snapshot_on_process_start: bool = True
    resource_snapshot_on_foreground_change: bool = True
    collect_window_titles: bool = False


@dataclass
class RetentionConfig:
    events_days: int = 180
    sessions_days: int = 365
    resource_samples_days: int = 90


@dataclass
class PatternsConfig:
    minimum_observation_days: int = 14
    minimum_context_occurrences: int = 10
    launch_frequency_threshold: float = 0.80
    time_bucket_minutes: int = 60
    eligible_day_types: List[str] = field(default_factory=lambda: ["weekday", "weekend"])


@dataclass
class ResourcesConfig:
    high_memory_percent: float = 15.0
    high_system_memory_percent: float = 85.0
    high_cpu_percent: float = 80.0
    sustained_observation_count: int = 3


@dataclass
class AutomationConfig:
    enabled: bool = False
    mode: str = "off"
    require_rule_approval: bool = True
    prompt_timeout_seconds: int = 10
    no_response_action: str = "skip"
    prevent_duplicate_instances: bool = True
    launch_missed_window_seconds: int = 0


@dataclass
class UIConfig:
    theme: str = "light"
    accent_color: str = "#635BFF"
    start_minimized: bool = False
    show_tray_icon: bool = True


@dataclass
class LLMConfig:
    enabled: bool = False
    provider: str = "none"
    share_raw_events: bool = False


@dataclass
class AppConfig:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    collection: CollectionConfig = field(default_factory=CollectionConfig)
    retention: RetentionConfig = field(default_factory=RetentionConfig)
    patterns: PatternsConfig = field(default_factory=PatternsConfig)
    resources: ResourcesConfig = field(default_factory=ResourcesConfig)
    automation: AutomationConfig = field(default_factory=AutomationConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


import logging

logger = logging.getLogger(__name__)


def _toml_format_value(val: Any) -> str:
    """Format a Python value into a valid TOML string literal."""
    if isinstance(val, bool):
        return "true" if val else "false"
    elif isinstance(val, int):
        return str(val)
    elif isinstance(val, float):
        return f"{val:.1f}" if val.is_integer() else str(val)
    elif isinstance(val, str):
        # Escape backslashes, quotes, and newlines
        escaped = val.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
        return f'"{escaped}"'
    elif isinstance(val, list):
        items = [_toml_format_value(x) for x in val]
        return f"[{', '.join(items)}]"
    return f'"{str(val)}"'


def render_config_toml(config: AppConfig) -> str:
    """Serialize AppConfig into a cleanly formatted TOML document string."""
    return f"""# Desktop Intelligence - Configuration File

[general]
app_name = {_toml_format_value(config.general.app_name)}
config_version = {_toml_format_value(config.general.config_version)}
log_level = {_toml_format_value(config.general.log_level)}
timezone = {_toml_format_value(config.general.timezone)}

[paths]
data_dir = {_toml_format_value(config.paths.data_dir)}
log_dir = {_toml_format_value(config.paths.log_dir)}

[collection]
enable_process_start_events = {_toml_format_value(config.collection.enable_process_start_events)}
enable_foreground_events = {_toml_format_value(config.collection.enable_foreground_events)}
enable_application_inventory = {_toml_format_value(config.collection.enable_application_inventory)}
enable_system_error_events = {_toml_format_value(config.collection.enable_system_error_events)}
idle_timeout_seconds = {_toml_format_value(config.collection.idle_timeout_seconds)}
idle_check_interval_seconds = {_toml_format_value(config.collection.idle_check_interval_seconds)}
resource_snapshot_on_process_start = {_toml_format_value(config.collection.resource_snapshot_on_process_start)}
resource_snapshot_on_foreground_change = {_toml_format_value(config.collection.resource_snapshot_on_foreground_change)}
collect_window_titles = {_toml_format_value(config.collection.collect_window_titles)}

[retention]
events_days = {_toml_format_value(config.retention.events_days)}
sessions_days = {_toml_format_value(config.retention.sessions_days)}
resource_samples_days = {_toml_format_value(config.retention.resource_samples_days)}

[patterns]
minimum_observation_days = {_toml_format_value(config.patterns.minimum_observation_days)}
minimum_context_occurrences = {_toml_format_value(config.patterns.minimum_context_occurrences)}
launch_frequency_threshold = {_toml_format_value(config.patterns.launch_frequency_threshold)}
time_bucket_minutes = {_toml_format_value(config.patterns.time_bucket_minutes)}
eligible_day_types = {_toml_format_value(config.patterns.eligible_day_types)}

[resources]
high_memory_percent = {_toml_format_value(config.resources.high_memory_percent)}
high_system_memory_percent = {_toml_format_value(config.resources.high_system_memory_percent)}
high_cpu_percent = {_toml_format_value(config.resources.high_cpu_percent)}
sustained_observation_count = {_toml_format_value(config.resources.sustained_observation_count)}

[automation]
enabled = {_toml_format_value(config.automation.enabled)}
mode = {_toml_format_value(config.automation.mode)}
require_rule_approval = {_toml_format_value(config.automation.require_rule_approval)}
prompt_timeout_seconds = {_toml_format_value(config.automation.prompt_timeout_seconds)}
no_response_action = {_toml_format_value(config.automation.no_response_action)}
prevent_duplicate_instances = {_toml_format_value(config.automation.prevent_duplicate_instances)}
launch_missed_window_seconds = {_toml_format_value(config.automation.launch_missed_window_seconds)}

[ui]
theme = {_toml_format_value(config.ui.theme)}
accent_color = {_toml_format_value(config.ui.accent_color)}
start_minimized = {_toml_format_value(config.ui.start_minimized)}
show_tray_icon = {_toml_format_value(config.ui.show_tray_icon)}

[llm]
enabled = {_toml_format_value(config.llm.enabled)}
provider = {_toml_format_value(config.llm.provider)}
share_raw_events = {_toml_format_value(config.llm.share_raw_events)}
"""


def save_config(config: AppConfig, path: Path) -> None:
    """Save AppConfig to path atomically with proper TOML escaping."""
    target_path = Path(path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    toml_str = render_config_toml(config)

    temp_file = target_path.parent / f".tmp_{target_path.name}_{os.getpid()}"
    try:
        temp_file.write_text(toml_str, encoding="utf-8")
        temp_file.replace(target_path)
    except Exception:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except Exception:
                pass
        raise


def _filter_known_fields(cls, d: Dict[str, Any]) -> Dict[str, Any]:
    """Filter dictionary to only known dataclass fields, logging warnings for unknown keys."""
    if not isinstance(d, dict):
        return {}
    known = set(cls.__dataclass_fields__.keys())
    filtered = {}
    for k, v in d.items():
        if k in known:
            filtered[k] = v
        else:
            logger.warning("Ignoring unknown configuration key: %s.%s", cls.__name__, k)
    return filtered


def validate_config_dict(data: Dict[str, Any]) -> None:
    """Validate raw configuration dictionary, raising ConfigValidationError on any violation."""
    if not isinstance(data, dict):
        raise ConfigValidationError("Root configuration must be a mapping/table")

    # General validation
    gen = data.get("general", {})
    if not isinstance(gen, dict):
        raise ConfigValidationError("[general] must be a table")
    if "config_version" in gen:
        ver = gen["config_version"]
        if isinstance(ver, bool) or not isinstance(ver, int) or ver < 1:
            raise ConfigValidationError(f"[general].config_version must be integer >= 1, got {ver!r}")
    if "log_level" in gen:
        lvl = str(gen["log_level"]).upper()
        if lvl not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigValidationError(f"[general].log_level unknown: {gen['log_level']!r}")
    if "timezone" in gen:
        tz = str(gen["timezone"]).strip()
        if tz.lower() not in {"local", "utc"}:
            try:
                ZoneInfo(tz)
            except (ZoneInfoNotFoundError, Exception) as exc:
                raise ConfigValidationError(f"[general].timezone is invalid: {tz!r}") from exc

    # Collection validation
    col = data.get("collection", {})
    if not isinstance(col, dict):
        raise ConfigValidationError("[collection] must be a table")
    for b_field in [
        "enable_process_start_events", "enable_foreground_events", "enable_application_inventory",
        "enable_system_error_events", "resource_snapshot_on_process_start",
        "resource_snapshot_on_foreground_change", "collect_window_titles"
    ]:
        if b_field in col and (not isinstance(col[b_field], bool) or type(col[b_field]) is not bool):
            raise ConfigValidationError(f"[collection].{b_field} must be boolean, got {col[b_field]!r}")
    if "idle_timeout_seconds" in col:
        v = col["idle_timeout_seconds"]
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            raise ConfigValidationError(f"[collection].idle_timeout_seconds must be positive integer, got {v!r}")
    if "idle_check_interval_seconds" in col:
        v = col["idle_check_interval_seconds"]
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            raise ConfigValidationError(f"[collection].idle_check_interval_seconds must be positive integer, got {v!r}")

    # Retention validation
    ret = data.get("retention", {})
    if not isinstance(ret, dict):
        raise ConfigValidationError("[retention] must be a table")
    for r_field in ["events_days", "sessions_days", "resource_samples_days"]:
        if r_field in ret:
            v = ret[r_field]
            if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
                raise ConfigValidationError(f"[retention].{r_field} must be positive integer, got {v!r}")

    # Patterns validation
    pat = data.get("patterns", {})
    if not isinstance(pat, dict):
        raise ConfigValidationError("[patterns] must be a table")
    if "minimum_observation_days" in pat:
        v = pat["minimum_observation_days"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise ConfigValidationError(f"[patterns].minimum_observation_days must be integer >= 1, got {v!r}")
    if "minimum_context_occurrences" in pat:
        v = pat["minimum_context_occurrences"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise ConfigValidationError(f"[patterns].minimum_context_occurrences must be integer >= 1, got {v!r}")
    if "launch_frequency_threshold" in pat:
        v = pat["launch_frequency_threshold"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0.0 or v > 1.0:
            raise ConfigValidationError(f"[patterns].launch_frequency_threshold must be in range (0.0, 1.0], got {v!r}")
    if "time_bucket_minutes" in pat:
        v = pat["time_bucket_minutes"]
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0 or v > 1440:
            raise ConfigValidationError(f"[patterns].time_bucket_minutes must be between 1 and 1440, got {v!r}")
    if "eligible_day_types" in pat:
        v = pat["eligible_day_types"]
        if not isinstance(v, list) or not v or not set(v).issubset({"weekday", "weekend"}):
            raise ConfigValidationError(f"[patterns].eligible_day_types must be non-empty subset of ['weekday', 'weekend'], got {v!r}")

    # Resources validation
    res = data.get("resources", {})
    if not isinstance(res, dict):
        raise ConfigValidationError("[resources] must be a table")
    for pct_field in ["high_memory_percent", "high_system_memory_percent", "high_cpu_percent"]:
        if pct_field in res:
            v = res[pct_field]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0.0 or v > 100.0:
                raise ConfigValidationError(f"[resources].{pct_field} must be between 0.0 and 100.0, got {v!r}")
    if "sustained_observation_count" in res:
        v = res["sustained_observation_count"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise ConfigValidationError(f"[resources].sustained_observation_count must be integer >= 1, got {v!r}")

    # Automation validation
    aut = data.get("automation", {})
    if not isinstance(aut, dict):
        raise ConfigValidationError("[automation] must be a table")
    if "mode" in aut:
        v = str(aut["mode"]).lower()
        if v not in {"off", "prompt", "auto", "notify"}:
            raise ConfigValidationError(f"[automation].mode must be one of ['off', 'prompt', 'auto', 'notify'], got {aut['mode']!r}")
    if "no_response_action" in aut:
        v = str(aut["no_response_action"]).lower()
        if v not in {"skip", "launch"}:
            raise ConfigValidationError(f"[automation].no_response_action must be 'skip' or 'launch', got {aut['no_response_action']!r}")
    if "prompt_timeout_seconds" in aut:
        v = aut["prompt_timeout_seconds"]
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            raise ConfigValidationError(f"[automation].prompt_timeout_seconds must be positive integer, got {v!r}")

    # UI validation
    ui = data.get("ui", {})
    if not isinstance(ui, dict):
        raise ConfigValidationError("[ui] must be a table")
    if "theme" in ui:
        v = str(ui["theme"]).lower()
        if v not in {"light", "dark", "system"}:
            raise ConfigValidationError(f"[ui].theme must be one of ['light', 'dark', 'system'], got {ui['theme']!r}")
    if "accent_color" in ui:
        import re
        v = str(ui["accent_color"]).strip()
        if not re.match(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", v):
            raise ConfigValidationError(f"[ui].accent_color must be a valid hex color, got {ui['accent_color']!r}")


def load_config(path: Optional[Path] = None, fallback_on_missing: bool = True) -> AppConfig:
    """Load and validate configuration from TOML file.

    If path is None, looks for config.toml in current working directory.
    If the file does not exist:
      - If fallback_on_missing is True, returns default AppConfig.
      - If fallback_on_missing is False, raises FileNotFoundError.
    """
    if path is None:
        path = Path.cwd() / "config.toml"
    else:
        path = Path(path)

    if not path.exists():
        if fallback_on_missing:
            return AppConfig()
        raise FileNotFoundError(f"Configuration file not found: {path}")

    try:
        content = path.read_bytes()
        raw_data = tomllib.loads(content.decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigValidationError(f"Malformed TOML syntax in {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise ConfigValidationError(f"File {path} is not valid UTF-8: {exc}") from exc

    validate_config_dict(raw_data)

    aut_dict = raw_data.get("automation", {})
    filtered_aut = _filter_known_fields(AutomationConfig, aut_dict)
    if "mode" not in aut_dict:
        legacy_enabled = aut_dict.get("enabled", False)
        legacy_req_approval = aut_dict.get("require_rule_approval", True)
        if not legacy_enabled:
            filtered_aut["mode"] = "off"
            filtered_aut["enabled"] = False
        else:
            filtered_aut["enabled"] = True
            filtered_aut["mode"] = "prompt" if legacy_req_approval else "auto"
    else:
        mode_val = str(aut_dict["mode"]).lower()
        filtered_aut["mode"] = mode_val
        filtered_aut["enabled"] = (mode_val != "off")

    config = AppConfig(
        general=GeneralConfig(**_filter_known_fields(GeneralConfig, raw_data.get("general", {}))),
        paths=PathsConfig(**_filter_known_fields(PathsConfig, raw_data.get("paths", {}))),
        collection=CollectionConfig(**_filter_known_fields(CollectionConfig, raw_data.get("collection", {}))),
        retention=RetentionConfig(**_filter_known_fields(RetentionConfig, raw_data.get("retention", {}))),
        patterns=PatternsConfig(**_filter_known_fields(PatternsConfig, raw_data.get("patterns", {}))),
        resources=ResourcesConfig(**_filter_known_fields(ResourcesConfig, raw_data.get("resources", {}))),
        automation=AutomationConfig(**filtered_aut),
        ui=UIConfig(**_filter_known_fields(UIConfig, raw_data.get("ui", {}))),
        llm=LLMConfig(**_filter_known_fields(LLMConfig, raw_data.get("llm", {}))),
    )
    return config
