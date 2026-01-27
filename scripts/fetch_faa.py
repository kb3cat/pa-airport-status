#!/usr/bin/env python3
import json
import os
import re
import sys
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

import requests


# -----------------------------
# Airport list (PA regions)
# -----------------------------
# Notes:
# - ABP (Northeast Philadelphia) uses KPNE for METAR.
# - SCE (State College) uses KUNV for METAR.
AIRPORTS = [
  # Western
  {"code":"PIT","name":"Pittsburgh Intl","region":"Western","lat":40.4920,"lon":-80.2327,"metar":"KPIT"},
  {"code":"ERI","name":"Erie Intl","region":"Western","lat":42.0831,"lon":-80.1739,"metar":"KERI"},
  {"code":"LBE","name":"Arnold Palmer Regional","region":"Western","lat":40.2759,"lon":-79.4048,"metar":"KLBE"},
  {"code":"JST","name":"Johnstown–Cambria County","region":"Western","lat":40.3161,"lon":-78.8339,"metar":"KJST"},
  {"code":"DUJ","name":"DuBois Regional","region":"Western","lat":41.1783,"lon":-78.8987,"metar":"KDUJ"},

  # Central
  {"code":"MDT","name":"Harrisburg Intl","region":"Central","lat":40.1931,"lon":-76.7633,"metar":"KMDT"},
  {"code":"CXY","name":"Capital City","region":"Central","lat":40.2171,"lon":-76.8515,"metar":"KCXY"},
  {"code":"SCE","name":"State College Regional","region":"Central","lat":40.8493,"lon":-77.8487,"metar":"KUNV"},
  {"code":"IPT","name":"Williamsport Regional","region":"Central","lat":41.2421,"lon":-76.9211,"metar":"KIPT"},
  {"code":"AOO","name":"Altoona–Blair County","region":"Central","lat":40.2964,"lon":-78.3200,"metar":"KAOO"},
  {"code":"BFD","name":"Bradford Regional","region":"Central","lat":41.8031,"lon":-78.6401,"metar":"KBFD"},

  # Eastern
  {"code":"PHL","name":"Philadelphia Intl","region":"Eastern","lat":39.8729,"lon":-75.2437,"metar":"KPHL"},
  {"code":"ABP","name":"Northeast Philadelphia","region":"Eastern","lat":40.0819,"lon":-75.0106,"metar":"KPNE"},
  {"code":"ABE","name":"Lehigh Valley Intl","region":"Eastern","lat":40.6521,"lon":-75.4408,"metar":"KABE"},
  {"code":"AVP","name":"Wilkes-Barre/Scranton Intl","region":"Eastern","lat":41.3385,"lon":-75.7234,"metar":"KAVP"},
  {"code":"RDG","name":"Reading Regional","region":"Eastern","lat":40.3785,"lon":-75.9652,"metar":"KRDG"},
  {"code":"LNS","name":"Lancaster","region":"Eastern","lat":40.1217,"lon":-76.2961,"metar":"KLNS"},
  {"code":"MPO","name":"Pocono Mountains Municipal","region":"Eastern","lat":41.1375,"lon":-75.3789,"metar":"KMPO"},
]

REGION_ORDER = ["Western", "Central", "Eastern"]

PA_CODES = [a["code"] for a in AIRPORTS]
PA_SET = set(PA_CODES)


# -----------------------------
# FAA NAS Status parsing
# -----------------------------
FAA_AIRPORT_STATUS_XML = "https://nasstatus.faa.gov/api/airport-status-information"

def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag

def _iter_elements(root):
    for el in root.iter():
        el.tag = _strip_ns(el.tag)
        yield el

def fetch_airport_status_information():
    """
    Returns two dicts:
      closures: { "ABE": "<Reason string>" }
      impacts:  { "ABE": "<Reason string>" }   # delays/ground stops/other active airport events
    """
    closures = {}
    impacts = {}

    r = requests.get(FAA_AIRPORT_STATUS_XML, timeout=30)
    r.raise_for_status()

    text = r.text.strip()
    # Sometimes content may include a leading BOM or whitespace
    text = re.sub(r"^\ufeff", "", text)

    root = ET.fromstring(text)
    # normalize tags (strip namespaces)
    for _ in _iter_elements(root):
        pass

    # Common structure includes lists like:
    #  <Airport_Closure_List><Airport><ARPT>ABE</ARPT><Reason>...</Reason></Airport>...
    # and delay lists / ground stop lists etc.
    #
    # We'll scan for any "*_List" elements containing <Airport> children with <ARPT>.
    # If list name contains "Closure" => closures, else impacts.
    for list_el in root.iter():
        tag = list_el.tag or ""
        if not tag.endswith("_List"):
            continue

        is_closure_list = ("Closure" in tag) or ("Closures" in tag)
        for ap in list_el.findall(".//Airport"):
            arpt = ap.findtext("ARPT") or ap.findtext("Airport") or ap.findtext("ARPT_ID")
            if not arpt:
                continue
            arpt = arpt.strip().upper()
            if arpt not in PA_SET:
                continue

            reason = (ap.findtext("Reason") or ap.findtext("REASON") or "").strip()

            # If no explicit reason, try to capture the full text of the Airport node
            if not reason:
                reason = " ".join((ap.itertext() or [])).strip()
                reason = re.sub(r"\s+", " ", reason)

            if is_closure_list:
                closures[arpt] = reason
            else:
                # impacts can overlap; keep first if already populated
                impacts.setdefault(arpt, reason)

    return closures, impacts


# -----------------------------
# AviationWeather.gov METAR flight category
# -----------------------------
def fetch_flight_categories(metar_ids):
    """
    Returns dict like {"KABE":"VFR","KAVP":"IFR",...}
    Uses AWC Data API XML.
    """
    if not metar_ids:
        return {}

    ids_param = ",".join(metar_ids)
    url = f"https://aviationweather.gov/api/data/metar?format=xml&ids={ids_param}"

    r = requests.get(url, timeout=30)
    r.raise_for_status()

    cats = {}
    root = ET.fromstring(r.text)

    for metar in root.findall(".//METAR"):
        sid = metar.findtext("station_id")
        fc = metar.findtext("flight_category")
        if sid and fc:
            cats[sid.strip().upper()] = fc.strip().upper()

    return cats


# -----------------------------
# Build output JSON
# -----------------------------
def utc_now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

def build_regions():
    regions = {r: [] for r in REGION_ORDER}
    for a in AIRPORTS:
        regions[a["region"]].append({
            "code": a["code"],
            "name": a["name"],
            "lat": a["lat"],
            "lon": a["lon"],
        })
    return regions

def main():
    generated_utc = utc_now_str()

    # Default status objects
    airports_status = {
        code: {"code": code, "status": "OK", "closed": False, "closure_reason": "", "events": []}
        for code in PA_CODES
    }

    # FAA closures/impacts
    try:
        closures, impacts = fetch_airport_status_information()
    except Exception as e:
        # If FAA fetch fails, still emit status.json (page will show OK + categories)
        closures, impacts = {}, {}
        print(f"[WARN] FAA airport-status-information fetch failed: {e}", file=sys.stderr)

    for code, reason in closures.items():
        st = airports_status[code]
        st["status"] = "CLOSED"
        st["closed"] = True
        st["closure_reason"] = reason

    for code, reason in impacts.items():
        # If closed, keep it closed
        st = airports_status[code]
        if st.get("closed"):
            continue
        st["status"] = "IMPACT"
        st["closed"] = False
        # Keep in events (more future-proof)
        st["events"] = [{"type": "Impact", "reason": reason}]

    # METAR flight categories
    metar_ids = [a["metar"] for a in AIRPORTS if a.get("metar")]
    try:
        fc_map = fetch_flight_categories(metar_ids)
    except Exception as e:
        fc_map = {}
        print(f"[WARN] METAR fetch failed: {e}", file=sys.stderr)

    for a in AIRPORTS:
        code = a["code"]
        metar = (a.get("metar") or "").upper()
        airports_status[code]["flight_category"] = fc_map.get(metar, "UNK")

    out = {
        "generated_utc": generated_utc,
        "regions": build_regions(),
        "airports": airports_status,
        "source": "nasstatus.faa.gov/api/airport-status-information + aviationweather.gov METAR flight_category",
        "note": "Temporary closures/impacts from FAA NAS Status; flight categories from METAR.",
    }

    os.makedirs("docs", exist_ok=True)
    out_path = os.path.join("docs", "status.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print(f"Wrote {out_path} ({generated_utc})")

if __name__ == "__main__":
    main()
