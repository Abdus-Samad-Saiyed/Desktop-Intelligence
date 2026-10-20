import os
import sys
from pathlib import Path
import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from desktop_intelligence.config import AppConfig, load_config
from desktop_intelligence.paths import resolve_paths
from desktop_intelligence.storage.csv_store import CsvStore
from desktop_intelligence.ui.main_window import MainWindow
from desktop_intelligence.ui.theme import (
    ACCENT_PRESETS,
    generate_stylesheet,
    get_effective_theme,
    get_theme_palette,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def test_effective_theme_resolution():
    assert get_effective_theme("light") == "light"
    assert get_effective_theme("dark") == "dark"
    assert get_effective_theme("LIGHT") == "light"
    assert get_effective_theme("DARK") == "dark"
    assert get_effective_theme("system") in {"light", "dark"}
    # Graceful fallback for unknown strings
    assert get_effective_theme("nonexistent_theme") == "light"


def test_theme_palette_structure():
    light_p = get_theme_palette("light", "#6366F1")
    dark_p = get_theme_palette("dark", "#2563EB")

    required_keys = {
        "mode", "app_bg", "surface_bg", "border", "text_primary",
        "text_secondary", "sidebar_bg", "accent", "input_bg",
    }
    assert required_keys.issubset(set(light_p.keys()))
    assert required_keys.issubset(set(dark_p.keys()))

    assert light_p["mode"] == "light"
    assert dark_p["mode"] == "dark"
    assert light_p["accent"] == "#6366F1"
    assert dark_p["accent"] == "#2563EB"


def test_generate_stylesheet_tokens():
    light_css = generate_stylesheet("light", "#6366F1")
    assert "QMainWindow" in light_css
    assert "#F3F6FC" in light_css
    assert "#6366F1" in light_css

    dark_css = generate_stylesheet("dark", "#10B981")
    assert "QMainWindow" in dark_css
    assert "#0A0D16" in dark_css
    assert "#10B981" in dark_css


def test_main_window_theme_switching_and_persistence(qapp, tmp_path):
    paths = resolve_paths(
        data_dir_override=str(tmp_path / "data"),
        log_dir_override=str(tmp_path / "logs"),
        config_file_override=tmp_path / "config.toml",
    )
    paths.ensure_directories()
    paths.config_file.write_text("[general]\nconfig_version = 1\n", encoding="utf-8")
    store = CsvStore(paths)
    config = AppConfig()

    window = MainWindow(config=config, paths=paths, store=store)
    window.show()

    # Initial state should be light with default accent
    assert window.config.ui.theme == "light"

    # Switch to Dark mode and Teal accent
    window.apply_theme("dark", "#0D9488")
    assert window.config.ui.theme == "dark"
    assert window.config.ui.accent_color == "#0D9488"
    assert "#0A0D16" in window.styleSheet()
    assert "#0D9488" in window.styleSheet()

    # Persist config and inspect on disk
    window._persist_config()
    loaded = load_config(paths.config_file)
    assert loaded.ui.theme == "dark"
    assert loaded.ui.accent_color == "#0D9488"

    window.close()
