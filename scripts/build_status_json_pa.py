#!/usr/bin/env python3
import csv
import io
import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen

OUT_PATH = "docs/status.json"
UA = "PA-Airport-Status-GitHub/1.0"

# AviationWeather stations dataset (CSV)
# We query for PA stations.
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

def parse_stations_csv(csv_text: str):
    # Strip comment lines
    lines = []
    for ln in csv_text.splitlines():
        if ln.startswith("#"):
            continue
        if not ln.strip():
            continue
        lines.append(ln)

    if not lines:
        return []

    reader = csv.DictReader(io.StringIO("\n".join(lines)))
    return list(reader)

def as_float(x, default=None):
    try:
        return float(x)
    except Exception:
        return default

def code_from_station_id(station_id: str) -> str:
    sid = station_id.strip().upper()
    # If ICAO starts with K, use 3-letter code (matches your UI)
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

def looks_like_airport_metar_station(row: dict) -> bool:
    """
    Keep stations that are likely airport METAR stations.
    Practical rules:
      - station_id length 3 or 4
      - has lat/lon
      - site type not obviously something else (stations dataset is mostly OK)
    """
    sid = (row.get("station_id") or "").strip().upper()
    if not sid or len(sid) not in (3, 4):
        return False

    lat = as_float(row.get("latitude"))
    lon = as_float(row.get("longitude"))
    if lat is None or lon is None:
        return False

    # Many airport IDs are Kxxx (4 chars) or 3-letter FAA IDs.
    return True

def region_from_lon(lon: float) -> str:
    """
    Simple West/Central/East split for PA by longitude.
    Adjust thresholds any time.
    """
    if lon <= -78.5:
        return "Western"
    if lon <= -76.5:
        return "Central"
    return "Eastern"

def main():
    text = fetch_text(STATIONS_PA_CSV_URL)
    rows = parse_stations_csv(text)

    regions = {"Western": [], "Central": [], "Eastern": []}
    airports = {}

    for r in rows:
        st = (r.get("state") or "").strip().upper()
        if st != "PA":
            continue
        if not looks_like_airport_metar_station(r):
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

        airports[code] = {
            "icao": icao,
            "status": "OK",
            "flight_category": "UNK",
            "impact_reason": "",
            "metar_raw": ""   # will be filled by your update workflow
        }

    # Sort region lists by code for consistency
    for k in regions.keys():
        regions[k].sort(key=lambda x: x["code"])

    out = {
        "generated_utc": now_utc_iso_z(),
        "regions": regions,
        "airports": airports
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
        f.write("\n")

    print(f"Wrote {OUT_PATH} with {len(airports)} PA stations.")

if __name__ == "__main__":
    main()
