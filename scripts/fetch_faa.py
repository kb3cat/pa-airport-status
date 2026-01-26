#!/usr/bin/env python3
import json
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

FAA_XML_URL = "https://nasstatus.faa.gov/api/airport-status-information"

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

OUT_PATH = Path("docs/status.json")

def _t(el):
    return (el.text or "").strip()

def fetch_xml(url: str, timeout=30, retries=3) -> bytes:
    last = None
    headers = {"User-Agent": "PA-Airport-StatusBoard/1.0", "Accept": "application/xml,text/xml,*/*;q=0.9"}
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(2)
    raise RuntimeError(f"Failed to fetch FAA feed: {last}")

def parse_delay_types(root):
    events = {}
    for dt in root.iterfind(".//Delay_type"):
        name = _t(dt.find("./Name"))
        if name:
            events[name] = dt
    return events

def extract_closures(dt):
    out = {}
    for a in dt.findall(".//Airport_Closure_List//Airport"):
        code = _t(a.find("./ARPT"))
        reason = _t(a.find("./Reason"))
        if code:
            out[code] = reason or "Closed (reason not provided)"
    return out

def extract_programs(dt, list_path, item_tag):
    out = {}
    for p in dt.findall(f".//{list_path}//{item_tag}"):
        code = _t(p.find("./ARPT"))
        if not code:
            continue
        reason = _t(p.find("./Reason"))
        avg = _t(p.find("./Avg_delay")) or _t(p.find("./AvgDelay")) or ""
        out[code] = {"reason": reason, "avg_delay": avg}
    return out

def main():
    xml_bytes = fetch_xml(FAA_XML_URL)
    root = ET.fromstring(xml_bytes)
    events = parse_delay_types(root)

    closures = extract_closures(events.get("Airport Closures", ET.Element("x")))
    ground_stops = extract_programs(events.get("Ground Stop Programs", ET.Element("x")), "Ground_Stop_List", "Program")
    gdps = extract_programs(events.get("Ground Delay Programs", ET.Element("x")), "Ground_Delay_List", "Program")
    arr_delays = extract_programs(events.get("Arrival Delay", ET.Element("x")), "Arrival_Delay_List", "Airport")
    dep_delays = extract_programs(events.get("Departure Delay", ET.Element("x")), "Departure_Delay_List", "Airport")
    deicing = extract_programs(events.get("Deicing", ET.Element("x")), "Deicing_List", "Airport")

    monitored = {}
    codes = {a["code"] for region in AIRPORTS.values() for a in region}
    for code in sorted(codes):
        monitored[code] = {
            "code": code,
            "closed": code in closures,
            "closure_reason": closures.get(code, ""),
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
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
