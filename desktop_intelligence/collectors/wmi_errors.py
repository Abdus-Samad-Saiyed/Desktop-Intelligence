"""WMI and COM error classifier and diagnostic guidance."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional


WBEM_ERRORS: Dict[int, Dict[str, str]] = {
    0x80041003: {
        "code_name": "WBEM_E_ACCESS_DENIED",
        "reason_code": "ACCESS_DENIED_0x80041003",
        "severity": "warning",
        "reason": "Win32_ProcessStartTrace requires administrative privileges or specific WMI namespace permissions.",
        "impact": "Process launch detection falls back to polling mode (sub-second processes may be missed).",
        "remediation": "Run Desktop Intelligence as Administrator or configure WMI security permissions in wmimgmt.msc.",
    },
    0x80041010: {
        "code_name": "WBEM_E_INVALID_CLASS",
        "reason_code": "INVALID_CLASS_0x80041010",
        "severity": "error",
        "reason": "WMI class Win32_ProcessStartTrace is not registered on this Windows installation.",
        "impact": "Kernel process trace unavailable; falling back to event query polling.",
        "remediation": "Re-register WMI repository using winmgmt /salvagerepository.",
    },
    0x8004100E: {
        "code_name": "WBEM_E_INVALID_NAMESPACE",
        "reason_code": "INVALID_NAMESPACE_0x8004100E",
        "severity": "error",
        "reason": "WMI namespace root\\cimv2 does not exist or is corrupted.",
        "impact": "WMI event collection is unavailable.",
        "remediation": "Repair WMI repository using winmgmt /resetrepository.",
    },
    0x8004106C: {
        "code_name": "WBEM_E_QUOTA_VIOLATION",
        "reason_code": "QUOTA_VIOLATION_0x8004106C",
        "severity": "warning",
        "reason": "WMI provider exceeded memory or handle quota.",
        "impact": "WMI event queries throttled; falling back to event query polling.",
        "remediation": "Restart the Windows Management Instrumentation service (winmgmt).",
    },
}


def extract_hresult(exc: Exception) -> Optional[int]:
    """Attempt to extract 32-bit unsigned HRESULT from COM or WMI exception."""
    if hasattr(exc, "hresult") and isinstance(exc.hresult, int):
        return exc.hresult & 0xFFFFFFFF
    if hasattr(exc, "args") and exc.args and isinstance(exc.args[0], int):
        return exc.args[0] & 0xFFFFFFFF

    msg = str(exc)
    hex_match = re.search(r"0x([0-9a-fA-F]{8})", msg)
    if hex_match:
        try:
            return int(hex_match.group(1), 16)
        except ValueError:
            pass

    dec_match = re.search(r"-214721\d{4}", msg)
    if dec_match:
        try:
            val = int(dec_match.group(0))
            return val & 0xFFFFFFFF
        except ValueError:
            pass

    return None


def classify_wmi_error(exc: Exception) -> Dict[str, Any]:
    """Classify a WMI exception into structured diagnostic details."""
    hresult = extract_hresult(exc)
    exc_type = type(exc).__name__
    exc_str = str(exc).lower()

    if hresult and hresult in WBEM_ERRORS:
        info = dict(WBEM_ERRORS[hresult])
        info["hresult"] = f"0x{hresult:08X}"
        return info

    if "access_denied" in exc_type.lower() or "access is denied" in exc_str or "0x80041003" in exc_str:
        info = dict(WBEM_ERRORS[0x80041003])
        info["hresult"] = "0x80041003"
        return info

    if "invalid_class" in exc_type.lower() or "0x80041010" in exc_str:
        info = dict(WBEM_ERRORS[0x80041010])
        info["hresult"] = "0x80041010"
        return info

    return {
        "code_name": "WBEM_E_GENERIC",
        "reason_code": "WMI_GENERIC_ERROR",
        "severity": "warning",
        "reason": f"WMI subscription exception: {exc}",
        "impact": "Falling back to WMI event query polling.",
        "remediation": "Verify WMI service health and Windows Event Log for provider errors.",
        "hresult": f"0x{hresult:08X}" if hresult else "UNKNOWN",
    }
