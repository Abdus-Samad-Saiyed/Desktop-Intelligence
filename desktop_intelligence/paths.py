"""Path resolution for Desktop Intelligence."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


def get_default_base_dir() -> Path:
    """Return default user-level base directory for Desktop Intelligence."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "DesktopIntelligence"
    return Path.home() / ".desktop_intelligence"


@dataclass(frozen=True)
class ResolvedPaths:
    """Resolved directory and file paths."""
    base_dir: Path
    data_dir: Path
    log_dir: Path
    config_file: Path

    @property
    def activity_events_csv(self) -> Path:
        return self.data_dir / "activity_events.csv"

    @property
    def activity_sessions_csv(self) -> Path:
        return self.data_dir / "activity_sessions.csv"

    @property
    def resource_samples_csv(self) -> Path:
        return self.data_dir / "resource_samples.csv"

    @property
    def application_inventory_csv(self) -> Path:
        return self.data_dir / "application_inventory.csv"

    @property
    def recommendations_csv(self) -> Path:
        return self.data_dir / "recommendations.csv"

    @property
    def automation_log_csv(self) -> Path:
        return self.data_dir / "automation_log.csv"

    def ensure_directories(self) -> None:
        """Create data and log directories if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


def resolve_paths(
    data_dir_override: Optional[str] = None,
    log_dir_override: Optional[str] = None,
    config_file_override: Optional[Path] = None,
    config: Optional[Any] = None,
) -> ResolvedPaths:
    """Resolve operational paths safely, honouring [paths] configuration and user directory isolation."""
    base_dir = get_default_base_dir()

    # Priority: explicit argument > config.paths.data_dir > default (base_dir / 'data')
    if data_dir_override and str(data_dir_override).strip():
        data_dir = Path(os.path.expandvars(os.path.expanduser(str(data_dir_override).strip()))).resolve()
    elif config and hasattr(config, "paths") and getattr(config.paths, "data_dir", None) and str(config.paths.data_dir).strip():
        data_dir = Path(os.path.expandvars(os.path.expanduser(str(config.paths.data_dir).strip()))).resolve()
    else:
        data_dir = (base_dir / "data").resolve()

    if log_dir_override and str(log_dir_override).strip():
        log_dir = Path(os.path.expandvars(os.path.expanduser(str(log_dir_override).strip()))).resolve()
    elif config and hasattr(config, "paths") and getattr(config.paths, "log_dir", None) and str(config.paths.log_dir).strip():
        log_dir = Path(os.path.expandvars(os.path.expanduser(str(config.paths.log_dir).strip()))).resolve()
    else:
        log_dir = (base_dir / "logs").resolve()

    if config_file_override:
        config_file = config_file_override.resolve()
    else:
        user_config = (base_dir / "config.toml").resolve()
        if not user_config.exists():
            template_config = (Path.cwd() / "config.toml").resolve()
            if template_config.exists() and template_config != user_config:
                try:
                    base_dir.mkdir(parents=True, exist_ok=True)
                    user_config.write_text(template_config.read_text(encoding="utf-8"), encoding="utf-8")
                except Exception:
                    pass
        config_file = user_config

    return ResolvedPaths(
        base_dir=base_dir,
        data_dir=data_dir,
        log_dir=log_dir,
        config_file=config_file,
    )

