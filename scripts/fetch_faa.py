#!/usr/bin/env python3
import json
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

FAA_XML_URL = "https://nasstatus.faa.gov/api/airport-status-information"
OUT_PATH = Path("docs/status.json")

AIRPORTS = {
  "Western": [
    {"code":"PIT","name":"Pittsburgh Intl"},
    {"code":"ERI","name":"Erie Intl"},
    {"code":"LBE","name":"Arnold Palmer Regional (Latrobe)"},
    {"code":"JST","name":"Johnstown–Cambria County"},
    {"code":"DUJ","name":"DuBois Regional"},
  ],
  "Central": [
    {"code":"MDT","name":"Harrisburg Intl"},
    {"code":"CXY","name":"Capital City"},
    {"code":"SCE","name":"State College Regional"},
    {"code":"IPT","name":"Williamsport Regional"},
    {"code":"AOO","name":"Altoona–Blair County"},
    {"code":"BFD","name":"Bradford Regional"},
  ],
  "Eastern": [
    {"code":"PHL","name":"Philadelphia Intl"},
    {"code":"ABP","name":"Northeast Philadelphia"},
    {"code":"ABE","name":"Lehigh Valley Intl"},
    {"code":"AVP","name":"Wilkes-Barre/Scranton Intl"},
    {"code":"RDG","name":"Reading Regional"},
    {"code":"LNS","name":"Lancaster"},
    {"code":"MPO","name":"Pocono Mountains Municipal"},
  ],
}

# Closure-ish hints; FAA sometimes reports snow closures in non-closure buckets.
CLOSE_HINTS = ("closed", "closure", "snow", "ice", "field", "runway", "plow")
IMPACT_HINTS = ("delay", "deicing", "ground stop", "gdp", "arrival", "departure")

def t(el):
    return (el.text or "").strip() if el is not None else ""

def fetch_xml(url: str, timeout=30, retries=3) -> bytes:
    last = None
    headers = {
        "User-Agent": "PA-Airport-StatusBoard/1.2",
        "Accept": "application/xml,text/xml,*/*;q=0.9",
    }
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(2)
    raise RuntimeError(f"Failed to fetch FAA feed after {retries} tries: {last}")

def looks_like_closed(text_value: str) -> bool:
    s = (text_value or "").lower()
    return any(k in s for k in CLOSE_HINTS)

def parse_all_events(root):
    """
    Returns a list of normalized event entries across ALL Delay_type blocks.

    Each entry:
      {
        "type": "<Delay_type Name>",
        "arpt": "<ARPT code>",
        "reason": "<Reason text>",
        "avg_delay": "<Avg_delay if present>"
      }

    FAA XML varies; we scan for any element that has a child named ARPT.
    """
    events = []

    for dt in root.iterfind(".//Delay_type"):
        dtype_name = t(dt.find("./Name")) or "Unknown"

        # Find any element under this Delay_type that contains an ARPT child
        for node in dt.iter():
            arpt_el = node.find("./ARPT")
            if arpt_el is None:
                continue

            arpt = t(arpt_el).upper()
            if not arpt:
                continue

            reason = t(node.find("./Reason"))
            avg = t(node.find("./Avg_delay")) or t(node.find("./AvgDelay"))

            events.append({
                "type": dtype_name,
                "arpt": arpt,
                "reason": reason,
                "avg_delay": avg,
            })

    return events

def summarize_for_airport(code: str, all_events):
    """
    For a given airport code (IATA-like in this feed), collect all related events.

    Determine:
      - closed: True if any event type or reason indicates closure
      - impacts: list of events (for display)
      - closure_reason: joined closure reasons for display
    """
    code = code.upper()
    matches = [e for e in all_events if e["arpt"] == code]

    # Determine closed:
    closed_reasons = []
    for e in matches:
        type_l = (e["type"] or "").lower()
        reason_l = (e["reason"] or "").lower()

        # If FAA explicitly calls it a closure-type, trust that
        if "closure" in type_l:
            if e["reason"]:
                closed_reasons.append(e["reason"])
            else:
                closed_reasons.append(f"{e['type']}")
            continue

        # Or if the reason looks like an operational closure
        if looks_like_closed(e["reason"]) or "closed" in reason_l:
            closed_reasons.append(e["reason"] or e["type"])

    closed = len([r for r in closed_reasons if r.strip()]) > 0

    # De-dup closure reasons while preserving order
    seen = set()
    uniq_closed = []
    for r in closed_reasons:
        rr = (r or "").strip()
        if rr and rr not in seen:
            uniq_closed.append(rr)
            seen.add(rr)

    # Impacts: show everything we found (even if not closed) so you have transparency
    # De-dup same type+reason combos
    seen_ev = set()
    impacts = []
    for e in matches:
        key = (e["type"], e["reason"], e["avg_delay"])
        if key in seen_ev:
            continue
        seen_ev.add(key)
        impacts.append(e)

    closure_reason = " | ".join(uniq_closed) if uniq_closed else ""

    # classify overall status for UI
    # CLOSED > IMPACT > OK
    has_any_event = len(impacts) > 0
    status = "OK"
    if closed:
        status = "CLOSED"
    elif has_any_event:
        status = "IMPACT"

    return {
        "closed": closed,
        "status": status,
        "closure_reason": closure_reason,
        "events": impacts,  # list of {type, reason, avg_delay}
    }

def main():
    xml_bytes = fetch_xml(FAA_XML_URL)
    root = ET.fromstring(xml_bytes)

    all_events = parse_all_events(root)

    codes = {a["code"] for region in AIRPORTS.values() for a in region}
    airports_out = {}

    for code in sorted(codes):
        summary = summarize_for_airport(code, all_events)
        airports_out[code] = {
            "code": code,
            "status": summary["status"],        # OK / IMPACT / CLOSED
            "closed": summary["closed"],
            "closure_reason": summary["closure_reason"],
            "events": summary["events"],        # for display/debug
        }

    payload = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "regions": AIRPORTS,
        "airports": airports_out,
        "source": "FAA NAS Status airport-status-information",
        "note": "Board scans all Delay_type blocks and marks CLOSED if any closure-type or closure-like reason is present (matches FAA UI behavior).",
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
