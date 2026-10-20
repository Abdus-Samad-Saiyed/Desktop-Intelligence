"""Application inventory discovery from Windows Registry and Start Menu shortcuts."""

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Set

from desktop_intelligence.collectors.base import Clock, SystemClock
from desktop_intelligence.models import InventoryItem, format_utc_iso

logger = logging.getLogger(__name__)


def normalize_app_key(display_name: str, exe_path: str = "") -> str:
    """Generate a stable deduplication key for an application entry."""
    if exe_path:
        norm_path = os.path.normpath(exe_path).lower().strip()
        if norm_path:
            return norm_path
    return display_name.lower().strip()


def resolve_shortcut_target(lnk_path: str) -> str:
    """Resolve a .lnk Windows shortcut to its target executable path."""
    if sys.platform != "win32":
        return str(lnk_path)
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortcut(str(lnk_path))
            target = getattr(shortcut, "TargetPath", "")
            if target and target.strip():
                return target.strip()
        finally:
            pythoncom.CoUninitialize()
    except Exception as exc:
        logger.debug("Failed to resolve shortcut %s: %s", lnk_path, exc)
    return str(lnk_path)


class ApplicationInventoryScanner:
    """Discovers installed software and correlates with recorded observation history."""

    def __init__(self, clock: Optional[Clock] = None):
        self.clock = clock or SystemClock()

    def scan_windows_registry(self) -> List[Dict[str, str]]:
        """Query Windows uninstall registry hives for installed applications."""
        if sys.platform != "win32":
            return []

        import winreg

        results: List[Dict[str, str]] = []
        hives = [
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]

        for hive, subkey in hives:
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    count, _, _ = winreg.QueryInfoKey(key)
                    for i in range(count):
                        try:
                            sub_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, sub_name) as app_key:
                                try:
                                    name, _ = winreg.QueryValueEx(app_key, "DisplayName")
                                    name = str(name).strip()
                                    if not name:
                                        continue
                                except (FileNotFoundError, OSError):
                                    continue

                                # Filter out system components and updates if flag is explicitly set
                                try:
                                    system_component, _ = winreg.QueryValueEx(app_key, "SystemComponent")
                                    if system_component == 1:
                                        continue
                                except (FileNotFoundError, OSError):
                                    pass

                                try:
                                    loc, _ = winreg.QueryValueEx(app_key, "InstallLocation")
                                except (FileNotFoundError, OSError):
                                    loc = ""

                                try:
                                    icon, _ = winreg.QueryValueEx(app_key, "DisplayIcon")
                                    exe_path = icon.split(",")[0].strip('"') if icon else ""
                                except (FileNotFoundError, OSError):
                                    exe_path = ""

                                results.append({
                                    "display_name": name,
                                    "exe_path": exe_path,
                                    "source": "registry",
                                })
                        except Exception:
                            continue
            except FileNotFoundError:
                continue
            except Exception as exc:
                logger.debug("Error querying registry key %s: %s", subkey, exc)

        return results

    def scan_start_menu_shortcuts(self) -> List[Dict[str, str]]:
        """Scan Start Menu directories for .lnk shortcuts."""
        results: List[Dict[str, str]] = []
        search_dirs: List[Path] = []

        appdata = os.environ.get("APPDATA")
        if appdata:
            search_dirs.append(Path(appdata) / r"Microsoft\Windows\Start Menu\Programs")

        progdata = os.environ.get("PROGRAMDATA")
        if progdata:
            search_dirs.append(Path(progdata) / r"Microsoft\Windows\Start Menu\Programs")

        for sdir in search_dirs:
            if not sdir.exists():
                continue
            try:
                for lnk in sdir.rglob("*.lnk"):
                    # Ignore uninstaller shortcuts
                    stem = lnk.stem
                    if "uninstall" in stem.lower():
                        continue
                    resolved_exe = resolve_shortcut_target(str(lnk))
                    results.append({
                        "display_name": stem,
                        "exe_path": resolved_exe,
                        "source": "start_menu",
                    })
            except Exception as exc:
                logger.debug("Error scanning start menu directory %s: %s", sdir, exc)

        return results

    def build_inventory(
        self,
        raw_items: Optional[List[Dict[str, str]]] = None,
        observed_launch_counts: Optional[Dict[str, int]] = None,
        last_launch_timestamps: Optional[Dict[str, str]] = None,
        existing_first_seen: Optional[Dict[str, str]] = None,
    ) -> List[InventoryItem]:
        """Aggregate discovery from all sources and correlate with observation statistics."""
        if raw_items is None:
            raw_items = self.scan_windows_registry() + self.scan_start_menu_shortcuts()

        now_ts = format_utc_iso(self.clock.now_utc())
        launch_counts = observed_launch_counts or {}
        last_launches = last_launch_timestamps or {}
        first_seen_map = existing_first_seen or {}

        # Deduplicate items
        merged: Dict[str, Dict[str, Any]] = {}

        for item in raw_items:
            d_name = item.get("display_name", "").strip()
            if not d_name:
                continue

            exe = item.get("exe_path", "").strip()
            source = item.get("source", "manual")

            key = normalize_app_key(d_name, exe)

            if key not in merged:
                merged[key] = {
                    "display_name": d_name,
                    "exe_path": exe,
                    "sources": {source},
                }
            else:
                merged[key]["sources"].add(source)
                if not merged[key]["exe_path"] and exe:
                    merged[key]["exe_path"] = exe

        inventory: List[InventoryItem] = []
        for key, entry in merged.items():
            d_name = entry["display_name"]
            exe = entry["exe_path"]
            source_str = ";".join(sorted(entry["sources"]))

            # Look up launch metrics using various plausible keys
            exe_name = Path(exe).name.lower() if exe else ""
            counts = (
                launch_counts.get(d_name.lower())
                or launch_counts.get(exe.lower())
                or launch_counts.get(exe_name)
                or 0
            )

            last_ts = (
                last_launches.get(d_name.lower())
                or last_launches.get(exe.lower())
                or last_launches.get(exe_name)
                or ""
            )

            first_seen = first_seen_map.get(key) or now_ts

            inventory.append(
                InventoryItem(
                    observed_ts_utc=now_ts,
                    display_name=d_name,
                    exe_path=exe,
                    inventory_source=source_str,
                    first_seen_ts_utc=first_seen,
                    last_observed_launch_ts_utc=last_ts,
                    observed_launch_count=counts,
                )
            )

        # Sort alphabetically by display name
        inventory.sort(key=lambda x: x.display_name.lower())
        return inventory
