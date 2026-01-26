#!/usr/bin/env python3
import json
import time
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

# Server-rendered “Active Airport Events” list (reliably contains closures)
NASS_LIST_URL = "https://nasstatus.faa.gov/list"
# Secondary: XML feed
FAA_XML_URL = "https://nasstatus.faa.gov/api/airport-status-information"

OUT_PATH = Path("docs/status.json")

# NOTE: lat/lon are in decimal degrees (W is negative lon)
AIRPORTS = {
  "Western": [
    {"code":"PIT","name":"Pittsburgh Intl",              "lat":40.4920, "lon":-80.2327},
    {"code":"ERI","name":"Erie Intl",                    "lat":42.0831, "lon":-80.1739},
    {"code":"LBE","name":"Arnold Palmer Regional",       "lat":40.2759, "lon":-79.4048},
    {"code":"JST","name":"Johnstown–Cambria County",     "lat":40.3161, "lon":-78.8339},
    {"code":"DUJ","name":"DuBois Regional",              "lat":41.1783, "lon":-78.8987},
  ],
  "Central": [
    {"code":"MDT","name":"Harrisburg Intl",              "lat":40.1931, "lon":-76.7633},
    {"code":"CXY","name":"Capital City",                 "lat":40.2171, "lon":-76.8515},
    {"code":"SCE","name":"State College Regional",       "lat":40.8493, "lon":-77.8487},
    {"code":"IPT","name":"Williamsport Regional",        "lat":41.2421, "lon":-76.9211},
    {"code":"AOO","name":"Altoona–Blair County",         "lat":40.2964, "lon":-78.3200},
    {"code":"BFD","name":"Bradford Regional",            "lat":41.8031, "lon":-78.6401},
  ],
  "Eastern": [
    {"code":"PHL","name":"Philadelphia Intl",            "lat":39.8729, "lon":-75.2437},
    # Your closure code is ABP, but the field is Northeast Philadelphia (IATA: PNE).
    # We’re using the physical location of Northeast Philadelphia Airport for the marker.
    {"code":"ABP","name":"Northeast Philadelphia",       "lat":40.0819, "lon":-75.0106},
    {"code":"ABE","name":"Lehigh Valley Intl",           "lat":40.6521, "lon":-75.4408},
    {"code":"AVP","name":"Wilkes-Barre/Scranton Intl",   "lat":41.3385, "lon":-75.7234},
    {"code":"RDG","name":"Reading Regional",             "lat":40.3785, "lon":-75.9652},
    {"code":"LNS","name":"Lancaster",                    "lat":40.1217, "lon":-76.2961},
    {"code":"MPO","name":"Pocono Mountains Municipal",   "lat":41.1375, "lon":-75.3789},
  ],
}

def fetch_text(url: str, timeout=30, retries=3) -> str:
    last = None
    headers = {
        "User-Agent": "PA-Airport-StatusBoard/3.1",
        "Accept": "text/html,*/*;q=0.8",
    }
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            last = e
            time.sleep(2)
    raise RuntimeError(f"Failed to fetch {url}: {last}")

def fetch_bytes(url: str, timeout=30, retries=3) -> bytes:
    last = None
    headers = {
        "User-Agent": "PA-Airport-StatusBoard/3.1",
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
    raise RuntimeError(f"Failed to fetch {url}: {last}")

def _t(el):
    return (el.text or "").strip() if el is not None else ""

def parse_list_closures(list_html: str) -> dict:
    """
    Parse https://nasstatus.faa.gov/list for Airport Closure occurrences.
    We search for an airport code near the text 'Airport Closure'.
    """
    closures = {}
    h = re.sub(r"\s+", " ", list_html)

    # Typical pattern includes >CODE< somewhere near 'Airport Closure'
    for m in re.finditer(r">([A-Z0-9]{3,4})<[^>]*>[^<]*Airport Closure", h):
        code = m.group(1).upper()
        closures[code] = "Airport Closure"
    return closures

def parse_xml_closures(xml_bytes: bytes) -> dict:
    """
    Secondary: XML feed closure list.
    Returns dict: { "ABE": "reason..." }
    """
    closures = {}
    root = ET.fromstring(xml_bytes)
    for dt in root.iterfind(".//Delay_type"):
        name = _t(dt.find("./Name"))
        if name != "Airport Closures":
            continue
        for a in dt.findall(".//Airport_Closure_List//Airport"):
            code = _t(a.find("./ARPT")).upper()
            reason = _t(a.find("./Reason"))
            if code:
                closures[code] = reason or "Airport Closure"
    return closures

def main():
    # Primary: server-rendered list page
    list_html = fetch_text(NASS_LIST_URL)
    list_closures = parse_list_closures(list_html)

    # Secondary: XML feed closures
    xml_bytes = fetch_bytes(FAA_XML_URL)
    xml_closures = parse_xml_closures(xml_bytes)

    codes = {a["code"] for region in AIRPORTS.values() for a in region}
    airports_out = {}

    for code in sorted(codes):
        # Authority order: list page > xml feed
        closed_reason = ""
        closed = False

        if code in list_closures:
            closed = True
            closed_reason = list_closures[code]
        elif code in xml_closures:
            closed = True
            closed_reason = xml_closures[code]

        status = "CLOSED" if closed else "OK"

        airports_out[code] = {
            "code": code,
            "status": status,
            "closed": closed,
            "closure_reason": closed_reason,
            "events": []  # (future) parse impacts from XML if you want
        }

    payload = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "regions": AIRPORTS,     # <-- this includes lat/lon now
        "airports": airports_out,
        "source": "nasstatus.faa.gov/list + airport-status-information",
        "note": "Temporary closures sourced from NAS Status list page first, with XML as fallback. Regions include lat/lon for map markers.",
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
