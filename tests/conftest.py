import os
import sys
from pathlib import Path
import pytest

# Set offscreen platform before PySide6 loads
os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication(["desktop_intelligence", "-platform", "offscreen"])
    yield app


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Isolate tests from real user directories so tests never modify real user data."""
    fake_localappdata = tmp_path / "localappdata"
    fake_localappdata.mkdir(parents=True, exist_ok=True)
    fake_appdata = tmp_path / "appdata"
    fake_appdata.mkdir(parents=True, exist_ok=True)
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("LOCALAPPDATA", str(fake_localappdata))
    monkeypatch.setenv("APPDATA", str(fake_appdata))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOME", str(fake_home))
    yield
