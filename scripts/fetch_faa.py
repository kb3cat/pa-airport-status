#!/usr/bin/env python3
import json
import os
import re
import sys
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
import requests


# -----------------------------
# Airport list (PA)
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


FAA_AIRPORT_STATUS_XML = "https://nasstatus.faa.gov/api/airport-status-information"


# -----------------------------
def utc_now_str():
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
# FAA closures
# -----------------------------
def fetch_airport_status_information():
    closures = {}
    impacts = {}

    r = requests.get(FAA_AIRPORT_STATUS_XML, timeout=30)
    r.raise_for_status()

    text = re.sub(r"^\ufeff", "", r.text.strip())
    root = ET.fromstring(text)

    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}",1)[1]

    for lst in root.iter():
        if not lst.tag.endswith("_List"):
            continue

        is_closure = "Closure" in lst.tag

        for ap in lst.findall(".//Airport"):
            arpt = ap.findtext("ARPT","").strip().upper()
            if not arpt:
                continue

            reason = (ap.findtext("Reason") or "").strip()
            if not reason:
                reason = " ".join(ap.itertext()).strip()

            if is_closure:
                closures[arpt] = reason
            else:
                impacts[arpt] = reason

    return closures, impacts


# -----------------------------
# METAR Flight Category (NOAA ADDS XML)
# -----------------------------
def fetch_flight_categories(metar_ids):
    ids = ",".join(metar_ids)

    url = (
        "https://aviationweather.gov/adds/dataserver_current/httpparam"
        f"?dataSource=metars&requestType=retrieve&format=xml"
        f"&stationString={ids}&hoursBeforeNow=2"
    )

    r = requests.get(url, timeout=45)
    r.raise_for_status()

    root = ET.fromstring(r.text)

    cats = {}

    for metar in root.findall(".//METAR"):
        station = metar.findtext("station_id","").strip().upper()
        fc = metar.findtext("flight_category","").strip().upper()
        if station and fc:
            cats[station] = fc

    return cats


# -----------------------------
# Main
# -----------------------------
def main():
    generated_utc = utc_now_str()

    airports_status = {
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

    # FAA status
    try:
        closures, impacts = fetch_airport_status_information()
        print(f"[INFO] FAA closures: {len(closures)}, impacts: {len(impacts)}")
    except Exception as e:
        print(f"[WARN] FAA status fetch failed: {e}")
        closures, impacts = {}, {}

    for code, reason in closures.items():
        if code in airports_status:
            airports_status[code]["status"] = "CLOSED"
            airports_status[code]["closed"] = True
            airports_status[code]["closure_reason"] = reason

    for code, reason in impacts.items():
        if code in airports_status and not airports_status[code]["closed"]:
            airports_status[code]["status"] = "IMPACT"
            airports_status[code]["events"] = [{"type":"Impact","reason":reason}]

    # METAR categories
    metar_ids = [a["metar"] for a in AIRPORTS]
    try:
        cats = fetch_flight_categories(metar_ids)
        print(f"[INFO] METAR flight categories: {len(cats)} of {len(metar_ids)}")
    except Exception as e:
        print(f"[WARN] METAR fetch failed: {e}")
        cats = {}

    for a in AIRPORTS:
        code = a["code"]
        metar = a["metar"]
        airports_status[code]["flight_category"] = cats.get(metar,"UNK")

    out = {
        "generated_utc": generated_utc,
        "regions": build_regions(),
        "airports": airports_status,
        "source": "nasstatus.faa.gov + aviationweather.gov ADDS XML",
        "note": "Closures from FAA NAS Status. Flight categories from NOAA ADDS METAR feed."
    }

    os.makedirs("docs", exist_ok=True)
    with open("docs/status.json","w",encoding="utf-8") as f:
        json.dump(out,f,indent=2)

    print("Wrote docs/status.json")


if __name__ == "__main__":
    main()
