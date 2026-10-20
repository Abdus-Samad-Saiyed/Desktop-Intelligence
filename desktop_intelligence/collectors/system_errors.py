"""Windows application error and reliability event collector."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import re
import subprocess
import sys
import threading
import time
from typing import Dict, List, Optional, Tuple

from desktop_intelligence.collectors.base import Clock, SystemClock
from desktop_intelligence.models import format_utc_iso

logger = logging.getLogger(__name__)

# Standard Windows Event Log type constants
EVENTLOG_SUCCESS = 0x0000
EVENTLOG_ERROR_TYPE = 0x0001
EVENTLOG_WARNING_TYPE = 0x0002
EVENTLOG_INFORMATION_TYPE = 0x0004
EVENTLOG_AUDIT_SUCCESS = 0x0008
EVENTLOG_AUDIT_FAILURE = 0x0010

SUPPORTED_ERROR_PROVIDERS = {
    "Application Error",
    "Application Hang",
    "Windows Error Reporting",
}


@dataclass
class SystemErrorEvent:
    event_ts_utc: str
    app_name: str
    error_code: str
    faulting_module: str
    description: str
    source: str = "Windows_Application_Error"
    severity: str = "Error"
    provider: str = "Application Error"
    event_id: int = 1000


def is_supported_reliability_event(source_name: str, event_id: int, event_type: int) -> bool:
    """Determine whether an event record represents a genuine application failure or error report.

    Explicitly excludes informational service events (e.g., service starts, background heartbeats)
    that happen to share Event ID 1000 or other IDs under non-crash providers.
    """
    if not source_name:
        return False

    clean_source = source_name.strip()

    # Informational events are only eligible if from Windows Error Reporting
    if event_type == EVENTLOG_INFORMATION_TYPE and clean_source != "Windows Error Reporting":
        return False

    # Check known genuine error providers
    if clean_source in SUPPORTED_ERROR_PROVIDERS:
        if clean_source == "Application Error" and event_id in {1000, 1001}:
            return True
        if clean_source == "Application Hang" and event_id in {1002}:
            return True
        if clean_source == "Windows Error Reporting" and event_id in {1001}:
            return True

    # Generic Application log errors with error severity
    if event_type == EVENTLOG_ERROR_TYPE and "Error" in clean_source:
        return True

    return False


def parse_application_error_message(msg: str, provider: str = "") -> Dict[str, str]:
    """Parse Windows Event ID 1000/1001/1002 message text into structured fields.

    Handles English and localized variants, application crashes, application hangs,
    and Windows Error Reporting / LiveKernel diagnostic payloads safely.
    Preserves honest metadata without fabricating missing fields.
    """
    fields = {
        "app_name": "unknown",
        "error_code": "",
        "faulting_module": "",
        "description": msg.strip()[:240] if msg else "",
    }
    if not msg:
        return fields

    # 1. Faulting application name (Application Error ID 1000)
    app_match = re.search(r"Faulting application name:\s*([^,\r\n]+)", msg, re.IGNORECASE)
    if app_match:
        fields["app_name"] = app_match.group(1).strip()
    else:
        # Check Application Hang (ID 1002) pattern:
        # "The program notepad.exe version 10.0.19041.1 stopped interacting with Windows..."
        hang_match = re.search(r"The program\s+([^,\s]+)\s+version\s+[^,\r\n]+\s+stopped interacting", msg, re.IGNORECASE)
        if hang_match:
            fields["app_name"] = hang_match.group(1).strip()

    # 2. Faulting module name
    mod_match = re.search(r"Faulting module name:\s*([^,\r\n]+)", msg, re.IGNORECASE)
    if mod_match:
        fields["faulting_module"] = mod_match.group(1).strip()

    # 3. Exception code
    code_match = re.search(r"Exception code:\s*([^,\r\n]+)", msg, re.IGNORECASE)
    if code_match:
        fields["error_code"] = code_match.group(1).strip()

    # 4. Windows Error Reporting / Kernel diagnostic telemetry (Event ID 1001)
    if "LiveKernelEvent" in msg:
        fields["app_name"] = "System / OS Report"
        # Extract bugcheck / error code (e.g. 1b8, 1a8, 1b0)
        lk_code = re.search(r"LiveKernelEvent\s+(?:Not available|[^\s]+(?:\s+[^\s]+)?)\s+\d+\s+([0-9a-fA-F]+)", msg, re.IGNORECASE)
        if not lk_code:
            lk_code = re.search(r"Kernel_([0-9a-fA-F]+)_", msg, re.IGNORECASE)
        if lk_code:
            code_hex = lk_code.group(1)
            fields["error_code"] = f"0x{code_hex.upper()}" if not code_hex.lower().startswith("0x") else code_hex
        # Detect watchdog or driver component from report path if present
        mod_match = re.search(r"LiveKernelReports\\([A-Za-z0-9_]+)\\", msg)
        if mod_match:
            fields["faulting_module"] = mod_match.group(1)

    elif "BlueScreen" in msg:
        fields["app_name"] = "System / OS Report"
        bs_code = re.search(r"BlueScreen\s+(?:Not available|[^\s]+(?:\s+[^\s]+)?)\s+\d+\s+([0-9a-fA-F]+)", msg, re.IGNORECASE)
        if not bs_code:
            bs_code = re.search(r"BlueScreen\s+.*?\s+([0-9a-fA-F]{1,8})\b", msg, re.IGNORECASE)
        if bs_code:
            code_hex = bs_code.group(1)
            fields["error_code"] = f"0x{code_hex.upper()}" if not code_hex.lower().startswith("0x") else code_hex

    elif "APPCRASH" in msg or "BEX" in msg or "MoAppCrash" in msg:
        # Standard WER crash bucket
        p1 = re.search(r"(?:P1|Problem signature:\s*P1):\s*([^\r\n\s]+)", msg, re.IGNORECASE)
        if p1 and p1.group(1).lower() not in {"not available", "unknown"}:
            fields["app_name"] = p1.group(1).strip()
        p4 = re.search(r"(?:P4|Problem signature:\s*P4):\s*([^\r\n\s]+)", msg, re.IGNORECASE)
        if p4 and not fields["faulting_module"] and p4.group(1).lower() not in {"not available", "unknown"}:
            fields["faulting_module"] = p4.group(1).strip()
        p7 = re.search(r"(?:P7|Problem signature:\s*P7):\s*([^\r\n\s]+)", msg, re.IGNORECASE)
        if p7 and not fields["error_code"] and p7.group(1).lower() not in {"not available", "unknown"}:
            fields["error_code"] = p7.group(1).strip()

    # If provider is explicitly Windows Error Reporting and application could not be identified
    if provider == "Windows Error Reporting" or ("Windows Error Reporting" in msg and fields["app_name"] == "unknown"):
        if fields["app_name"] == "unknown":
            fields["app_name"] = "Windows Error Reporting"

    return fields


_ERRORS_CACHE: Optional[Tuple[List[SystemErrorEvent], str]] = None
_ERRORS_CACHE_LOCK = threading.Lock()
_ERRORS_CACHE_TIME = 0.0


def clear_errors_cache() -> None:
    """Clear in-memory cached reliability errors."""
    global _ERRORS_CACHE, _ERRORS_CACHE_TIME
    with _ERRORS_CACHE_LOCK:
        _ERRORS_CACHE = None
        _ERRORS_CACHE_TIME = 0.0


def query_recent_application_errors(
    max_records: int = 50,
    clock: Optional[Clock] = None,
    force_refresh: bool = False,
    cache_ttl_seconds: float = 60.0,
) -> Tuple[List[SystemErrorEvent], str]:
    """Query recent Windows Application Error records (Event ID 1000/1002/1001).

    Uses a thread-safe in-memory cache (default 60s) to keep GUI operations non-blocking.
    Filters strictly for genuine application errors and hangs, cleanly excluding
    informational service status events (e.g. Codex sandbox service heartbeats).
    Returns a tuple of (events_list, diagnostic_status).
    """
    global _ERRORS_CACHE, _ERRORS_CACHE_TIME

    if not force_refresh:
        with _ERRORS_CACHE_LOCK:
            if _ERRORS_CACHE is not None and (time.time() - _ERRORS_CACHE_TIME) < cache_ttl_seconds:
                return _ERRORS_CACHE

    events, status = _fetch_recent_application_errors(max_records=max_records, clock=clock)

    with _ERRORS_CACHE_LOCK:
        _ERRORS_CACHE = (events, status)
        _ERRORS_CACHE_TIME = time.time()

    return events, status


def parse_event_xml(xml_str: str) -> Optional[SystemErrorEvent]:
    """Parse real Windows Event Log XML (EvtRenderEventXml) for Event ID 1000/1001/1002."""
    if not xml_str or not xml_str.strip():
        return None

    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_str)
    except Exception as exc:
        logger.debug("Failed to parse Event XML: %s", exc)
        return None

    ns = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}

    sys_el = root.find("e:System", ns)
    if sys_el is None:
        sys_el = root.find("System")
        ns = {}

    provider_el = sys_el.find("e:Provider", ns) if sys_el is not None else None
    provider_name = provider_el.attrib.get("Name", "") if provider_el is not None else ""

    eid_text = sys_el.findtext("e:EventID", default="", namespaces=ns) if sys_el is not None else ""
    try:
        event_id = int(eid_text)
    except ValueError:
        event_id = 1000

    time_el = sys_el.find("e:TimeCreated", ns) if sys_el is not None else None
    sys_time = time_el.attrib.get("SystemTime", "") if time_el is not None else ""
    event_ts_utc = sys_time if sys_time else format_utc_iso(datetime.now(timezone.utc))

    data_dict: Dict[str, str] = {}
    data_list: List[str] = []
    data_query = "e:EventData/e:Data" if ns else "EventData/Data"
    for d_el in root.findall(data_query, ns):
        d_name = d_el.attrib.get("Name")
        d_val = (d_el.text or "").strip()
        if d_name:
            data_dict[d_name.lower()] = d_val
        data_list.append(d_val)

    app_name = "unknown"
    faulting_module = "-"
    error_code = "-"
    severity = "Report"
    description = ""

    if event_id == 1000 or "application error" in provider_name.lower():
        severity = "Crash"
        app_name = data_dict.get("appname") or (data_list[0] if len(data_list) > 0 else "unknown")
        faulting_module = data_dict.get("faultmodulename") or (data_list[3] if len(data_list) > 3 else "-")
        raw_code = data_dict.get("exceptioncode") or (data_list[6] if len(data_list) > 6 else "-")
        if raw_code and not raw_code.lower().startswith("0x") and raw_code != "-":
            error_code = f"0x{raw_code.upper()}"
        else:
            error_code = raw_code
        description = f"Application crash in {app_name} (faulting module: {faulting_module}, code: {error_code})"

    elif event_id == 1002 or "application hang" in provider_name.lower():
        severity = "Hang"
        app_name = data_dict.get("appname") or data_dict.get("program") or (data_list[0] if len(data_list) > 0 else "unknown")
        faulting_module = "-"
        error_code = data_dict.get("hangtype") or "-"
        description = f"Application hang in {app_name} (stopped interacting with Windows)"

    elif event_id == 1001 or "windows error reporting" in provider_name.lower():
        severity = "Report"
        event_name = data_dict.get("eventname", "WER")
        p1 = data_dict.get("p1") or (data_list[0] if len(data_list) > 0 else "System / OS Report")
        p4 = data_dict.get("p4") or (data_list[3] if len(data_list) > 3 else "-")
        p7 = data_dict.get("p7") or (data_list[6] if len(data_list) > 6 else "-")

        app_name = p1
        faulting_module = p4 if p4.lower() not in {"not available", "unknown"} else "-"
        if p7 and not p7.lower().startswith("0x") and p7 != "-":
            error_code = f"0x{p7.upper()}"
        else:
            error_code = p7
        description = f"Windows error report for {app_name} (event: {event_name})"
    else:
        severity = "Error"
        app_name = data_dict.get("appname") or (data_list[0] if data_list else "unknown")
        description = f"Event {event_id} from {provider_name}"

    return SystemErrorEvent(
        event_ts_utc=event_ts_utc,
        app_name=app_name,
        error_code=error_code or "-",
        faulting_module=faulting_module or "-",
        description=description,
        source="Windows_Event_Log_XML",
        severity=severity,
        provider=provider_name or "Windows Event Log",
        event_id=event_id,
    )


def _fetch_recent_application_errors(
    max_records: int = 50,
    clock: Optional[Clock] = None,
) -> Tuple[List[SystemErrorEvent], str]:
    clk = clock or SystemClock()
    now_ts = format_utc_iso(clk.now_utc())

    if sys.platform != "win32":
        return [], "System event monitoring is only supported on Windows."

    # 1. Attempt EvtQuery + EvtRender (Windows Vista+ Event Log XML API)
    try:
        import win32evtlog  # type: ignore
        flags = win32evtlog.EvtQueryChannelPath | win32evtlog.EvtQueryReverseDirection
        xpath = "*[System[(EventID=1000 or EventID=1001 or EventID=1002)]]"
        q_handle = win32evtlog.EvtQuery("Application", flags, xpath)
        raw_events = win32evtlog.EvtNext(q_handle, max_records)
        events: List[SystemErrorEvent] = []
        for ev in raw_events:
            xml_str = win32evtlog.EvtRender(ev, win32evtlog.EvtRenderEventXml)
            parsed_evt = parse_event_xml(xml_str)
            if parsed_evt is not None:
                events.append(parsed_evt)

        return events, f"Operational (XML API retrieved {len(events)} events)"
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("EvtQuery XML query failed: %s; falling back to legacy EventLog", exc)

    # 2. Legacy pywin32 OpenEventLog fallback
    try:
        import win32evtlog  # type: ignore
        server = "localhost"
        logtype = "Application"
        flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
        hlog = win32evtlog.OpenEventLog(server, logtype)
        events: List[SystemErrorEvent] = []

        try:
            records = win32evtlog.ReadEventLog(hlog, flags, 0)
            while records and len(events) < max_records:
                for ev in records:
                    event_id = ev.EventID & 0xFFFF
                    event_type = getattr(ev, "EventType", 0)
                    source_name = getattr(ev, "SourceName", "") or ""

                    # Strictly filter for genuine reliability events
                    if not is_supported_reliability_event(source_name, event_id, event_type):
                        continue

                    msg = " ".join(str(s) for s in ev.StringInserts or [])
                    parsed = parse_application_error_message(msg, provider=source_name)

                    # Determine severity
                    if event_type == EVENTLOG_ERROR_TYPE:
                        severity = "Crash" if source_name == "Application Error" else ("Hang" if source_name == "Application Hang" else "Error")
                    elif event_type == EVENTLOG_WARNING_TYPE:
                        severity = "Warning"
                    else:
                        severity = "Report"

                    t_utc = ev.TimeGenerated.replace(tzinfo=timezone.utc)
                    events.append(
                        SystemErrorEvent(
                            event_ts_utc=format_utc_iso(t_utc),
                            app_name=parsed["app_name"],
                            error_code=parsed["error_code"] or "-",
                            faulting_module=parsed["faulting_module"] or "-",
                            description=parsed["description"] or msg[:240],
                            source="Windows_Application_Error",
                            severity=severity,
                            provider=source_name,
                            event_id=event_id,
                        )
                    )
                    if len(events) >= max_records:
                        break
                records = win32evtlog.ReadEventLog(hlog, flags, 0)
        finally:
            win32evtlog.CloseEventLog(hlog)

        return events, f"Operational (retrieved {len(events)} recent error events)"

    except ImportError:
        pass
    except Exception as exc:
        logger.debug("win32evtlog query failed: %s", exc)

    # Fallback to PowerShell Get-WinEvent with safety timeout
    try:
        ps_cmd = (
            f"Get-WinEvent -FilterHashtable @{{LogName='Application'; ProviderName=@('Application Error', 'Application Hang'); Level=2}} "
            f"-MaxEvents {max_records} -ErrorAction SilentlyContinue | "
            f"Select-Object -Property TimeCreated, ProviderName, Id, Message | ConvertTo-Json -Compress"
        )
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0 and res.stdout.strip():
            raw_json = json.loads(res.stdout.strip())
            items = raw_json if isinstance(raw_json, list) else [raw_json]
            events: List[SystemErrorEvent] = []
            for item in items:
                msg = item.get("Message", "")
                prov = item.get("ProviderName", "Application Error")
                parsed = parse_application_error_message(msg, provider=prov)
                eid = item.get("Id", 1000)
                events.append(
                    SystemErrorEvent(
                        event_ts_utc=now_ts,
                        app_name=parsed["app_name"],
                        error_code=parsed["error_code"] or "-",
                        faulting_module=parsed["faulting_module"] or "-",
                        description=parsed["description"],
                        source="Windows_Application_Error",
                        severity="Crash" if prov == "Application Error" else "Hang",
                        provider=prov,
                        event_id=eid,
                    )
                )
            return events, f"Operational (PowerShell retrieved {len(events)} error events)"
        else:
            return [], "No recent Application Error events recorded in Windows Event Log."

    except Exception as exc:
        return [], f"Application error source unavailable: {exc}"
