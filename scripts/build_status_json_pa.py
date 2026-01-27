#!/usr/bin/env python3
import csv
import io
import json
import os
from datetime import datetime, timezone
from urllib.request import Request, urlopen

OUT_PATH = "docs/status.json"
UA = "PA-Airport-Status-GitHub/1.0"

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
    if len(sid) == 4 and sid.startswith("K"):
        return sid[1:]  # KMDT -> MDT
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
    # West/Central/East split for PA
    if lon <= -78.5:
        return "Western"
    if lon <= -76.5:
        return "Central"
    return "Eastern"

def load_existing():
    if not os.path.isfile(OUT_PATH):
        return None
    try:
        with open(OUT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def main():
    existing = load_existing()
    existing_airports = (existing or {}).get("airports", {})

    text = fetch_text(STATIONS_PA_CSV_URL)
    rows = parse_csv_strip_comments(text)

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

        airports[code] = {
            "icao": icao,
            "status": prev.get("status", "OK"),
            "flight_category": prev.get("flight_category", "UNK"),
            "impact_reason": prev.get("impact_reason", ""),
            "metar_raw": prev.get("metar_raw", ""),
            "metar_time_utc": prev.get("metar_time_utc", ""),
        }

    for k in regions:
        regions[k].sort(key=lambda x: x["code"])

    out = {
        "generated_utc": now_utc_iso_z(),
        "regions": regions,
        "airports": airports
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
        f.write("\n")

    print(f"Wrote {OUT_PATH} with {len(airports)} stations.")

if __name__ == "__main__":
    main()
