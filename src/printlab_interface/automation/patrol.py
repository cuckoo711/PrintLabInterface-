"""Rule-based patrol of the printer state PrintLab already reports.

No model is called. It reads the status the adapter returns (the same read-only data the chat
tools see) and turns it into a short list of findings. The scheduler posts a mailbox message only
when the set of findings CHANGES, so a fault that stays does not repeat every minute.
"""
from __future__ import annotations

import json
from typing import Any

STALE_AFTER_S = 300
FAULT_STATES = {"FAILED", "PAUSE"}  # printer-reported states worth a human look; names come from PrintLab's own data


def _text(value: Any, limit: int = 120) -> str:
    return str(value if value is not None else "")[:limit]


def analyze(status: dict[str, Any]) -> list[dict[str, str]]:
    """Return findings as {key, severity, text}. Pure function of the status dict."""
    findings: list[dict[str, str]] = []
    if not status.get("online"):
        return [{"key": "printlab_offline", "severity": "warn", "text": "PrintLab is not reachable from the sidecar."}]
    data = status.get("data")
    device = data.get("device") if isinstance(data, dict) else None
    if not isinstance(device, dict):
        return [{"key": "no_device_data", "severity": "warn", "text": "PrintLab answered but reported no device section."}]
    if device.get("state") != "online":
        findings.append({"key": "device_not_online", "severity": "warn", "text": f"Device state is '{_text(device.get('state'))}'."})
    age = device.get("telemetry_age_seconds")
    if device.get("stale") or (isinstance(age, (int, float)) and age > STALE_AFTER_S):
        findings.append({"key": "telemetry_stale", "severity": "warn", "text": "Printer telemetry looks stale."})
    printer = device.get("printer")
    if not isinstance(printer, dict):
        findings.append({"key": "no_printer", "severity": "warn", "text": "No printer is reported."})
        return findings
    if printer.get("connected") is False:
        findings.append({"key": "printer_disconnected", "severity": "warn", "text": f"Printer '{_text(printer.get('name'))}' is not connected."})
    state = _text(printer.get("state")).upper()
    if state in FAULT_STATES:
        findings.append({"key": f"printer_state_{state.lower()}", "severity": "warn", "text": f"Printer state is {state}."})
    if printer.get("awaiting_plate_clear"):
        findings.append({"key": "awaiting_plate_clear", "severity": "info", "text": "The printer is waiting for the plate to be cleared."})
    hms = printer.get("hms_errors")
    if isinstance(hms, list):
        for item in hms[:10]:
            if not isinstance(item, dict):
                continue
            code = _text(item.get("full_code") or item.get("code"), 40)
            severity = "error" if isinstance(item.get("severity"), int) and item["severity"] <= 2 else "warn"
            note = _text(item.get("description"), 100)
            findings.append({"key": f"hms_{code}", "severity": severity, "text": f"Printer reports HMS {code}" + (f": {note}" if note else "") + "."})
    return findings


def fingerprint(findings: list[dict[str, str]]) -> str:
    return json.dumps(sorted(f["key"] for f in findings))


def worst(findings: list[dict[str, str]]) -> str:
    order = {"info": 0, "warn": 1, "error": 2}
    return max((f["severity"] for f in findings), key=lambda s: order[s], default="info")


def describe(findings: list[dict[str, str]]) -> tuple[str, str]:
    """Subject and body for a mailbox message."""
    if not findings:
        return "Patrol: all clear", "No findings in the latest printer status."
    subject = f"Patrol: {len(findings)} finding{'s' if len(findings) != 1 else ''}"
    return subject, "\n".join(f"- [{f['severity']}] {f['text']}" for f in findings)
