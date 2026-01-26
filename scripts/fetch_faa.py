#!/usr/bin/env python3
import json
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

# FAA NAS Status feed (XML)
FAA_XML_URL = "https://nasstatus.faa.gov/api/airport-status-information"

# Airports to display by region (edit anytime)
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

# Output goes into docs/ for GitHub Pages
OUT_PATH = Path("docs/status.json")

# Keywords that should cause the board to treat the airport as operationally CLOSED
# (These help match FAA UI "Airport Closure" cards even when the XML categorizes it differently.)
CLOSE_HINTS = ("closed", "snow", "field", "runway", "plow", "ice")

def _t(el):
    return (el.text or "").strip()

def fetch_xml(url: str, timeout=30, retries=3) -> bytes:
    last = None
    headers = {
        "User-Agent": "PA-Airport-StatusBoard/1.1",
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

def parse_delay_types(root):
    """
    FAA XML includes multiple <Delay_type> blocks with <Name> like:
      Airport Closures, Ground Stop Programs, Ground Delay Programs,
      Arrival Delay, Departure Delay, Deicing, etc.
    """
    events = {}
    for dt in root.iterfind(".//Delay_type"):
        name = _t(dt.find("./Name"))
        if name:
            events[name] = dt
    return events

def extract_closures(dt):
    """
    Pull closure airport codes + reason text.
    """
    out = {}
    for a in dt.findall(".//Airport_Closure_List//Airport"):
        code = _t(a.find("./ARPT"))
        reason = _t(a.find("./Reason"))
        if code:
            out[code] = reason or "Closed (reason not provided)"
    return out

def extract_programs(dt, list_path, item_tag):
    """
    Generic extractor for lists like Ground Stops / GDP / delays / deicing.
    These vary slightly, but many include ARPT + Reason + Avg_delay.
    """
    out = {}
    for p in dt.findall(f".//{list_path}//{item_tag}"):
        code = _t(p.find("./ARPT"))
        if not code:
            continue
        reason = _t(p.find("./Reason"))
        avg = _t(p.find("./Avg_delay")) or _t(p.find("./AvgDelay")) or ""
        out[code] = {"reason": reason, "avg_delay": avg}
    return out

def looks_like_closure(reason: str) -> bool:
    r = (reason or "").lower()
    return any(k in r for k in CLOSE_HINTS)

def decide_operational_closure(code: str, closures, ground_stops, gdps, arr_delays, dep_delays, deicing):
    """
    FAA sometimes displays "Airport Closure" on the UI even when the feed places
    the airport in delay/deicing/ground stop buckets. We treat it as CLOSED if:
      - It's in Airport Closures list OR
      - Any event reason contains closure hints (closed/snow/runway/field/ice/etc.)
    """
    reasons = []

    # True closures bucket
    if code in closures:
        reasons.append(closures.get(code, ""))

    # Other buckets that can indicate a practical closure
    for src in (ground_stops, gdps, arr_delays, dep_delays, deicing):
        ev = src.get(code)
        if ev:
            reason = ev.get("reason") or ""
            if looks_like_closure(reason):
                reasons.append(reason)

    if reasons:
        # De-dup while preserving order
        seen = set()
        uniq = []
        for r in reasons:
            rr = r.strip()
            if rr and rr not in seen:
                uniq.append(rr)
                seen.add(rr)
        return True, " | ".join(uniq) if uniq else "Closed (reason not provided)"

    return False, ""

def main():
    xml_bytes = fetch_xml(FAA_XML_URL)
    root = ET.fromstring(xml_bytes)
    events = parse_delay_types(root)

    # Extract known categories
    closures = extract_closures(events.get("Airport Closures", ET.Element("x")))
    ground_stops = extract_programs(events.get("Ground Stop Programs", ET.Element("x")),
                                    "Ground_Stop_List", "Program")
    gdps = extract_programs(events.get("Ground Delay Programs", ET.Element("x")),
                            "Ground_Delay_List", "Program")
    arr_delays = extract_programs(events.get("Arrival Delay", ET.Element("x")),
                                  "Arrival_Delay_List", "Airport")
    dep_delays = extract_programs(events.get("Departure Delay", ET.Element("x")),
                                  "Departure_Delay_List", "Airport")
    deicing = extract_programs(events.get("Deicing", ET.Element("x")),
                               "Deicing_List", "Airport")

    monitored = {}
    codes = {a["code"] for region in AIRPORTS.values() for a in region}

    for code in sorted(codes):
        closed, closure_reason = decide_operational_closure(
            code, closures, ground_stops, gdps, arr_delays, dep_delays, deicing
        )

        monitored[code] = {
            "code": code,
            "closed": closed,
            "closure_reason": closure_reason,
            "ground_stop": ground_stops.get(code),
            "gdp": gdps.get(code),
            "arrival_delay": arr_delays.get(code),
            "departure_delay": dep_delays.get(code),
            "deicing": deicing.get(code),
        }

    payload = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "regions": AIRPORTS,
        "airports": monitored,
        "source": "FAA NAS Status airport-status-information",
        "note": "Airports may be marked CLOSED if any FAA NAS event reason suggests operational closure (snow/field/runway/ice), matching NAS Status UI behavior.",
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
