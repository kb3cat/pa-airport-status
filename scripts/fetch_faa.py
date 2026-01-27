#!/usr/bin/env python3
import json
import os
import re
import sys
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
import requests


# -----------------------------
# PA Airports
# -----------------------------
AIRPORTS = [
  {"code":"PIT","name":"Pittsburgh Intl","region":"Western","lat":40.4920,"lon":-80.2327,"metar":"KPIT"},
  {"code":"ERI","name":"Erie Intl","region":"Western","lat":42.0831,"lon":-80.1739,"metar":"KERI"},
  {"code":"LBE","name":"Arnold Palmer Regional","region":"Western","lat":40.2759,"lon":-79.4048,"metar":"KLBE"},
  {"code":"JST","name":"Johnstown–Cambria County","region":"Western","lat":40.3161,"lon":-78.8339,"metar":"KJST"},
  {"code":"DUJ","name":"DuBois Regional","region":"Western","lat":41.1783,"lon":-78.8987,"metar":"KDUJ"},

  {"code":"MDT","name":"Harrisburg Intl","region":"Central","lat":40.1931,"lon":-76.7633,"metar":"KMDT"},
  {"code":"CXY","name":"Capital City","region":"Central","lat":40.2171,"lon":-76.8515,"metar":"KCXY"},
  {"code":"SCE","name":"State College Regional","region":"Central","lat":40.8493,"lon":-77.8487,"metar":"KUNV"},
  {"code":"IPT","name":"Williamsport Regional","region":"Central","lat":41.2421,"lon":-76.9211,"metar":"KIPT"},
  {"code":"AOO","name":"Altoona–Blair County","region":"Central","lat":40.2964,"lon":-78.3200,"metar":"KAOO"},
  {"code":"BFD","name":"Bradford Regional","region":"Central","lat":41.8031,"lon":-78.6401,"metar":"KBFD"},

  {"code":"PHL","name":"Philadelphia Intl","region":"Eastern","lat":39.8729,"lon":-75.2437,"metar":"KPHL"},
  {"code":"ABP","name":"Northeast Philadelphia","region":"Eastern","lat":40.0819,"lon":-75.0106,"metar":"KPNE"},
  {"code":"ABE","name":"Lehigh Valley Intl","region":"Eastern","lat":40.6521,"lon":-75.4408,"metar":"KABE"},
  {"code":"AVP","name":"Wilkes-Barre/Scranton Intl","region":"Eastern","lat":41.3385,"lon":-75.7234,"metar":"KAVP"},
  {"code":"RDG","name":"Reading Regional","region":"Eastern","lat":40.3785,"lon":-75.9652,"metar":"KRDG"},
  {"code":"LNS","name":"Lancaster","region":"Eastern","lat":40.1217,"lon":-76.2961,"metar":"KLNS"},
  {"code":"MPO","name":"Pocono Mountains Municipal","region":"Eastern","lat":41.1375,"lon":-75.3789,"metar":"KMPO"},
]

FAA_STATUS_URL = "https://nasstatus.faa.gov/api/airport-status-information"
NOAA_METAR_URL = "https://aviationweather.gov/adds/dataserver_current/httpparam"


# -----------------------------
def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def build_regions():
    regions = {}
    for a in AIRPORTS:
        regions.setdefault(a["region"], []).append({
            "code": a["code"],
            "name": a["name"],
            "lat": a["lat"],
            "lon": a["lon"]
        })
    return regions


# -----------------------------
# FAA closures / impacts
# -----------------------------
def fetch_faa_status():
    closures = {}
    impacts = {}

    r = requests.get(FAA_STATUS_URL, timeout=30)
    r.raise_for_status()

    root = ET.fromstring(r.text)

    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}",1)[1]

    for group in root.iter():
        if not group.tag.endswith("_List"):
            continue

        is_closure = "Closure" in group.tag

        for ap in group.findall(".//Airport"):
            code = (ap.findtext("ARPT") or "").strip().upper()
            if not code:
                continue

            reason = (ap.findtext("Reason") or "").strip()
            if not reason:
                reason = " ".join(ap.itertext()).strip()

            if is_closure:
                closures[code] = reason
            else:
                impacts[code] = reason

    return closures, impacts


# -----------------------------
# NOAA METAR Flight Category
# -----------------------------
def fetch_flight_categories(stations):
    ids = ",".join(stations)

    url = (
        NOAA_METAR_URL +
        f"?dataSource=metars&requestType=retrieve&format=xml"
        f"&stationString={ids}&hoursBeforeNow=2"
    )

    r = requests.get(url, timeout=45)
    r.raise_for_status()

    root = ET.fromstring(r.text)

    cats = {}
    for metar in root.findall(".//METAR"):
        station = (metar.findtext("station_id") or "").strip().upper()
        fc = (metar.findtext("flight_category") or "").strip().upper()
        if station and fc:
            cats[station] = fc

    return cats


# -----------------------------
# Main
# -----------------------------
def main():
    airports = {
        a["code"]: {
            "code": a["code"],
            "status": "OK",
            "closed": False,
            "closure_reason": "",
            "events": [],
            "flight_category": "UNK"
        }
        for a in AIRPORTS
    }

    try:
        closures, impacts = fetch_faa_status()
        print(f"[INFO] FAA closures: {len(closures)}, impacts: {len(impacts)}")
    except Exception as e:
        print(f"[WARN] FAA status fetch failed: {e}")
        closures, impacts = {}, {}

    for code, reason in closures.items():
        if code in airports:
            airports[code]["status"] = "CLOSED"
            airports[code]["closed"] = True
            airports[code]["closure_reason"] = reason

    for code, reason in impacts.items():
        if code in airports and not airports[code]["closed"]:
            airports[code]["status"] = "IMPACT"
            airports[code]["events"] = [{"type":"Impact","reason":reason}]

    metar_ids = [a["metar"] for a in AIRPORTS]

    try:
        cats = fetch_flight_categories(metar_ids)
        print(f"[INFO] METAR flight categories: {len(cats)} of {len(metar_ids)}")
    except Exception as e:
        print(f"[WARN] METAR fetch failed: {e}")
        cats = {}

    for a in AIRPORTS:
        airports[a["code"]]["flight_category"] = cats.get(a["metar"], "UNK")

    out = {
        "generated_utc": utc_now(),
        "regions": build_regions(),
        "airports": airports,
        "source": "nasstatus.faa.gov + NOAA ADDS XML",
        "note": "Closures from FAA NAS Status. Flight categories from NOAA ADDS METAR feed."
    }

    os.makedirs("docs", exist_ok=True)
    with open("docs/status.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print("Wrote docs/status.json")


if __name__ == "__main__":
    main()
