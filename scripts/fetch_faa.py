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

def fetch_text(url: str, timeout=30, retries=3) -> str:
    last = None
    headers = {
        "User-Agent": "PA-Airport-StatusBoard/3.0",
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
        "User-Agent": "PA-Airport-StatusBoard/3.0",
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
    Parse https://nasstatus.faa.gov/list for rows like:
      ABE, Airport Closure, <time>, ...
    Returns: { "ABE": "Airport Closure" } (we keep it simple & consistent)
    """
    closures = {}

    # The list page includes rows with airport code and event type text.
    # We’ll look for patterns like: >ABE< ... Airport Closure
    # Make whitespace predictable:
    h = re.sub(r"\s+", " ", list_html)

    # Find any occurrence of (CODE + Airport Closure) in close proximity.
    # Airport codes in NAS Status list are typically 3–4 chars; we use 3 for IATA-like
    for m in re.finditer(r">([A-Z0-9]{3})<[^>]*>[^<]*Airport Closure", h):
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
    # Primary closures from the server-rendered list view
    list_html = fetch_text(NASS_LIST_URL)
    list_closures = parse_list_closures(list_html)

    # Secondary closures from XML feed (sometimes helpful)
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
            "events": []  # keep for future expansion
        }

    payload = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "regions": AIRPORTS,
        "airports": airports_out,
        "source": "nasstatus.faa.gov/list + airport-status-information",
        "note": "Temporary closures are sourced from the NAS Status Active Airport Events list page first, with XML as fallback.",
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
