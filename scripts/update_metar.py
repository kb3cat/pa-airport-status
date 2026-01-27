#!/usr/bin/env python3
"""
update_metar.py
All-in-one builder + updater for docs/status.json (GitHub-only friendly)

What it does:
1) Pulls ALL Pennsylvania stations from AviationWeather stations dataset (CSV)
2) Builds regions: Western / Central / Eastern (simple lon bands)
3) Preserves manual fields from existing docs/status.json:
   - status
   - impact_reason
4) Pulls latest METAR for each station (last 2 hours) and writes:
   - flight_category
   - metar_raw
   - metar_time_utc
5) Writes docs/status.json
"""

import csv
import io
import json
import os
from datetime import datetime, timezone
from urllib.request import Request, urlopen

STATUS_PATH = "docs/status.json"
UA = "PA-Airport-Status-GitHub/1.0"

# Stations list (PA only)
STATIONS_PA_CSV_URL = (
    "https://aviationweather.gov/adds/dataserver_current/httpparam"
    "?dataSource=stations&requestType=retrieve&format=csv"
    "&stationString=~&state=PA"
)

def now_utc_iso_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def fetch_text(url: str, timeout: int = 25) -> str:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")

def parse_csv_strip_comments(csv_text: str):
    lines = []
    for ln in csv_text.splitlines():
        if ln.startswith("#"):
            continue
        if not ln.strip():
            continue
        lines.append(ln)
    if not lines:
        return []
    return list(csv.DictReader(io.StringIO("\n".join(lines))))

def as_float(x):
    try:
        return float(x)
    except Exception:
        return None

def code_from_station_id(station_id: str) -> str:
    sid = station_id.strip().upper()
    # KMDT -> MDT (matches your UI + click behavior)
    if len(sid) == 4 and sid.startswith("K"):
        return sid[1:]
    return sid

def icao_from_station_id(station_id: str) -> str:
    sid = station_id.strip().upper()
    if len(sid) == 4:
        return sid
    if len(sid) == 3:
        return "K" + sid
    return sid

def looks_like_metar_station(row: dict) -> bool:
    sid = (row.get("station_id") or "").strip().upper()
    if not sid or len(sid) not in (3, 4):
        return False
    lat = as_float(row.get("latitude"))
    lon = as_float(row.get("longitude"))
    if lat is None or lon is None:
        return False
    return True

def region_from_lon(lon: float) -> str:
    # Rough PA split. Adjust anytime.
    if lon <= -78.5:
        return "Western"
    if lon <= -76.5:
        return "Central"
    return "Eastern"

def load_existing():
    if not os.path.isfile(STATUS_PATH):
        return {}
    try:
        with open(STATUS_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def main():
    existing = load_existing()
    existing_airports = existing.get("airports", {}) if isinstance(existing.get("airports", {}), dict) else {}

    # -----------------------
    # 1) Build FULL PA list
    # -----------------------
    stations_csv = fetch_text(STATIONS_PA_CSV_URL)
    rows = parse_csv_strip_comments(stations_csv)

    regions = {"Western": [], "Central": [], "Eastern": []}
    airports = {}

    for r in rows:
        st = (r.get("state") or "").strip().upper()
        if st != "PA":
            continue
        if not looks_like_metar_station(r):
            continue

        sid = (r.get("station_id") or "").strip().upper()
        name = (r.get("station_name") or sid).strip()

        lat = as_float(r.get("latitude"))
        lon = as_float(r.get("longitude"))
        if lat is None or lon is None:
            continue

        code = code_from_station_id(sid)
        icao = icao_from_station_id(sid)
        region = region_from_lon(lon)

        # De-dupe
        if code in airports:
            continue

        regions[region].append({
            "code": code,
            "icao": icao,
            "name": name,
            "lat": lat,
            "lon": lon
        })

        prev = existing_airports.get(code, {}) if isinstance(existing_airports, dict) else {}

        # Preserve manual fields; do NOT wipe them
        airports[code] = {
            "icao": icao,
            "status": prev.get("status", "OK"),
            "impact_reason": prev.get("impact_reason", ""),
            # these will get updated below
            "flight_category": prev.get("flight_category", "UNK"),
            "metar_raw": prev.get("metar_raw", ""),
            "metar_time_utc": prev.get("metar_time_utc", "")
        }

    # Sort lists for stable diffs
    for k in regions:
        regions[k].sort(key=lambda x: x["code"])

    # -----------------------
    # 2) Pull METARs
    # -----------------------
    icaos = sorted({rec["icao"].strip().upper() for rec in airports.values() if isinstance(rec.get("icao"), str)})
    icaos = [i for i in icaos if len(i) == 4]

    metar_map = {}  # ICAO -> {flight_category, raw_text, observation_time}

    for part in chunks(icaos, 60):
        station_string = ",".join(part)
        url = (
            "https://aviationweather.gov/adds/dataserver_current/httpparam"
            "?dataSource=metars&requestType=retrieve&format=csv"
            f"&stationString={station_string}"
            "&hoursBeforeNow=2"
            "&mostRecentForEachStation=true"
        )
        metar_csv = fetch_text(url)
        mrows = parse_csv_strip_comments(metar_csv)

        for mr in mrows:
            sid = (mr.get("station_id") or "").strip().upper()
            if len(sid) != 4:
                continue
            metar_map[sid] = {
                "flight_category": (mr.get("flight_category") or "UNK").strip().upper(),
                "raw_text": (mr.get("raw_text") or "").strip(),
                "observation_time": (mr.get("observation_time") or "").strip(),
            }

    def norm_fc(fc: str) -> str:
        v = (fc or "UNK").strip().upper()
        return v if v in ("VFR", "MVFR", "IFR", "LIFR") else "UNK"

    # Update each airport with METAR info (do not touch status/impact_reason)
    for code, rec in airports.items():
        icao = (rec.get("icao") or "").strip().upper()
        m = metar_map.get(icao)
        if not m:
            rec["flight_category"] = norm_fc(rec.get("flight_category", "UNK"))
            # metar_raw/time left as-is if missing
            continue

        rec["flight_category"] = norm_fc(m.get("flight_category"))
        rec["metar_raw"] = m.get("raw_text", "").strip()
        rec["metar_time_utc"] = m.get("observation_time", "").strip()

    # -----------------------
    # 3) Write docs/status.json
    # -----------------------
    out = {
        "generated_utc": now_utc_iso_z(),
        "regions": regions,
        "airports": airports
    }

    os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
    with open(STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
        f.write("\n")

    print(f"Wrote {STATUS_PATH} with {len(airports)} PA stations. METARs found: {len(metar_map)}")

if __name__ == "__main__":
    main()
