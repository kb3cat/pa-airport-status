#!/usr/bin/env python3
import csv
import io
import json
import re
from datetime import datetime, timezone
from urllib.request import Request, urlopen

OUT_PATH = "docs/status.json"
UA = "PA-Airport-Status-GitHub/1.0"

# Pull *all* PA stations from AviationWeather's stations dataset (CSV)
# We filter state=PA and then keep likely airport METAR stations.
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
    # Strip comment lines starting with '#'
    lines = []
    for ln in csv_text.splitlines():
        if ln.startswith("#"):
            continue
        if ln.strip() == "":
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

def looks_like_airport_station(row: dict) -> bool:
    """
    Stations dataset includes airports + non-airport sites.
    We keep entries that look like an airport METAR station.

    Heuristics (safe + practical):
      - station_id is 4 chars (ICAO) OR 3 chars (some FAA IDs)
      - has latitude/longitude
      - NOT obviously marine buoy / mesonet / etc (usually not in PA list anyway)
    """
    sid = (row.get("station_id") or "").strip().upper()
    if not sid:
        return False

    # Keep ICAO-like (Kxxx) and a few others if present
    if len(sid) not in (3, 4):
        return False

    lat = as_float(row.get("latitude"))
    lon = as_float(row.get("longitude"))
    if lat is None or lon is None:
        return False

    # Most PA airports are Kxxx; keep them.
    # If we get some 3-letter IDs, keep them too.
    return True

def code_from_station_id(station_id: str) -> str:
    sid = station_id.strip().upper()
    # If ICAO starts with K, use 3-letter code for your UI consistency
    if len(sid) == 4 and sid.startswith("K"):
        return sid[1:]
    return sid

def region_from_lon(lon: float) -> str:
    """
    Auto-split into PEMA-ish West/Central/East using longitude bands.
    (Not perfect, but works well visually + operationally.)
    Adjust thresholds any time.
    """
    # PA roughly spans ~ -80.6 (west) to ~ -74.7 (east)
    if lon <= -78.5:
        return "Western"
    if lon <= -76.5:
        return "Central"
    return "Eastern"

def main():
    text = fetch_text(STATIONS_PA_CSV_URL)
    rows = parse_stations_csv(text)

    # Filter to airport-like stations
    kept = []
    for r in rows:
        st = (r.get("state") or "").strip().upper()
        if st != "PA":
            continue
        if looks_like_airport_station(r):
            kept.append(r)

    # Build regions + airports structures
    regions = {"Western": [], "Central": [], "Eastern": []}
    airports = {}

    for r in kept:
        sid = (r.get("station_id") or "").strip().upper()
        name = (r.get("station_name") or sid).strip()
        lat = as_float(r.get("latitude"), 40.9)
        lon = as_float(r.get("longitude"), -77.7)

        code = code_from_station_id(sid)
        region = region_from_lon(lon)

        # De-dupe by code (rare, but possible)
        if code in airports:
            continue

        regions[region].append({
            "code": code,
            "icao": sid if len(sid) == 4 else (("K" + sid) if len(sid) == 3 else sid),
            "name": name,
            "lat": lat,
            "lon": lon
        })

        airports[code] = {
            "icao": sid if len(sid) == 4 else (("K" + sid) if len(sid) == 3 else sid),
            "status": "OK",
            "flight_category": "UNK",
            "impact_reason": ""
        }

    # Sort each region by code for readability
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
