#!/usr/bin/env python3
import json
import os
import re
import sys
from datetime import datetime, timezone

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

FAA_AIRPORT_STATUS_XML = "https://nasstatus.faa.gov/api/airport-status-information"


# -----------------------------
# Helpers
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


# -----------------------------
# FAA NAS Status parsing
# -----------------------------
def fetch_airport_status_information():
    """
    Returns:
      closures: {"ABE": "<reason string>"}
      impacts:  {"ABE": "<reason string>"}   # delays/ground stops/other active airport events
    """
    import xml.etree.ElementTree as ET

    def strip_ns(tag: str) -> str:
        return tag.split("}", 1)[-1] if "}" in tag else tag

    closures = {}
    impacts = {}

    r = requests.get(FAA_AIRPORT_STATUS_XML, timeout=30)
    r.raise_for_status()

    text = r.text.strip()
    text = re.sub(r"^\ufeff", "", text)

    root = ET.fromstring(text)
    # strip namespaces in-place
    for el in root.iter():
        el.tag = strip_ns(el.tag)

    # Scan any "*_List" nodes that contain Airport children with ARPT codes.
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
            if not reason:
                # fallback: flatten airport node
                reason = " ".join((ap.itertext() or [])).strip()
                reason = re.sub(r"\s+", " ", reason)

            if is_closure_list:
                closures[arpt] = reason
            else:
                impacts.setdefault(arpt, reason)

    return closures, impacts


# -----------------------------
# METAR Flight Category (JSON)
# -----------------------------
def fetch_flight_categories(metar_ids):
    """
    Returns dict like {"KABE":"VFR","KAVP":"IFR",...}

    Uses AviationWeather.gov AWC Data API JSON to avoid XML parsing issues and
    handles 204 'no data' cleanly. Also sets a custom User-Agent (recommended for
    automated clients / helps reduce filtering).
    """
    if not metar_ids:
        return {}

    ids_param = ",".join(metar_ids)

    # hours= makes "no data" much less likely during quiet periods
    url = f"https://aviationweather.gov/api/data/metar?format=json&hours=6&ids={ids_param}"

    headers = {
        "User-Agent": "PA-Airport-StatusBoard/1.0 (GitHub Actions)"
    }

    r = requests.get(url, headers=headers, timeout=30)

    # 204 = valid request, no METAR returned
    if r.status_code == 204:
        print("[INFO] METAR API returned 204 (no data).", file=sys.stderr)
        return {}

    # Helpful diagnostics if something goes sideways
    if r.status_code >= 400:
        body = (r.text or "")[:500].replace("\n", " ")
        print(f"[WARN] METAR API HTTP {r.status_code}. Body (first 500): {body}", file=sys.stderr)

    r.raise_for_status()

    data = r.json()
    # Data is expected to be a list of METAR objects
    cats = {}

    if isinstance(data, dict):
        # Occasionally APIs wrap results; try to be resilient
        data = data.get("data") or data.get("metar") or data.get("METAR") or []

    if not isinstance(data, list):
        print("[WARN] METAR JSON unexpected shape; expected list.", file=sys.stderr)
        return {}

    for m in data:
        if not isinstance(m, dict):
            continue

        sid = (m.get("stationId") or m.get("station_id") or m.get("station") or "").strip().upper()
        # Newer JSON uses fltCat; some variants use flight_category
        fc = (m.get("fltCat") or m.get("flight_category") or m.get("flightCategory") or "").strip().upper()

        if sid and fc:
            cats[sid] = fc

    return cats


# -----------------------------
# Main
# -----------------------------
def main():
    generated_utc = utc_now_str()

    # Default status objects
    airports_status = {
        code: {
            "code": code,
            "status": "OK",
            "closed": False,
            "closure_reason": "",
            "events": []
        }
        for code in PA_CODES
    }

    # FAA closures/impacts
    try:
        closures, impacts = fetch_airport_status_information()
        print(f"[INFO] FAA closures: {len(closures)}; impacts: {len(impacts)}", file=sys.stderr)
    except Exception as e:
        closures, impacts = {}, {}
        print(f"[WARN] FAA airport-status-information fetch failed: {e}", file=sys.stderr)

    for code, reason in closures.items():
        st = airports_status[code]
        st["status"] = "CLOSED"
        st["closed"] = True
        st["closure_reason"] = reason

    for code, reason in impacts.items():
        st = airports_status[code]
        if st.get("closed"):
            continue
        st["status"] = "IMPACT"
        st["events"] = [{"type": "Impact", "reason": reason}]

    # METAR flight categories
    metar_ids = [a["metar"].upper() for a in AIRPORTS if a.get("metar")]
    try:
        fc_map = fetch_flight_categories(metar_ids)
        print(f"[INFO] METAR flight categories fetched: {len(fc_map)} of {len(metar_ids)}", file=sys.stderr)
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
        "source": "nasstatus.faa.gov/api/airport-status-information + aviationweather.gov METAR (JSON flight category)",
        "note": "Temporary closures/impacts from FAA NAS Status; flight categories from METAR (VFR/MVFR/IFR/LIFR).",
    }

    os.makedirs("docs", exist_ok=True)
    out_path = os.path.join("docs", "status.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print(f"Wrote {out_path} ({generated_utc})")


if __name__ == "__main__":
    main()
