#!/usr/bin/env python3
import csv
import io
import json
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen

OUT_PATH = "docs/status.json"
UA = "PA-Airport-Status-GitHub/1.0"

def now_utc_iso_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def fetch_text(url: str, timeout: int = 20) -> str:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")

def to_icao(code: str) -> str:
    code = code.strip().upper()
    if len(code) == 3:
        return "K" + code
    return code

# =========================
# FULL PA METAR LIST
# (3-letter IDs; we auto-map to ICAO "Kxxx")
# =========================
# Note: This list is intentionally "METAR-reporting airports" (ASOS/AWOS/contract obs).
# If a station ever stops reporting, update_status.py will mark it fetch-error/UNK.

REGIONS = {
    "Western": [
        "PIT","AGC","BVI","BTP","LBE","FWQ","AFJ","DUJ","FKL","GKJ","JST","AOO","ERI","IDI"
    ],
    "Central": [
        "MDT","CXY","MUI","THV","LNS","SEG","PTW","IPT","UNV","BFD","PSB","FIG","HZL","WBW"
    ],
    "Eastern": [
        "PHL","PNE","ABE","RDG","AVP","MPO","LOM","DYL","CKZ","UKT","MQS","NXX"
    ]
}

# AviationWeather "ADDS" stations dataset (CSV).
# This is a long-standing endpoint used for station metadata.
STATIONS_CSV_URL = (
    "https://aviationweather.gov/adds/dataserver_current/httpparam"
    "?dataSource=stations&requestType=retrieve&format=csv"
    "&stationString={stations}"
)

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
    rows = []
    for r in reader:
        rows.append(r)
    return rows

def main():
    # Flatten unique codes
    codes3 = []
    for region, lst in REGIONS.items():
        for c in lst:
            c = c.strip().upper()
            if c and c not in codes3:
                codes3.append(c)

    icaos = [to_icao(c) for c in codes3]
    station_param = ",".join(icaos)

    url = STATIONS_CSV_URL.format(stations=station_param)
    text = fetch_text(url)
    rows = parse_stations_csv(text)

    # Build a lookup keyed by station_id (ICAO)
    by_id = {}
    for r in rows:
        sid = (r.get("station_id") or "").strip().upper()
        if sid:
            by_id[sid] = r

    # Build regions array with {code,name,lat,lon}
    regions_out = {}
    airports_out = {}

    missing = []

    for region_name, lst in REGIONS.items():
        regions_out[region_name] = []
        for code3 in lst:
            icao = to_icao(code3)
            r = by_id.get(icao)
            if not r:
                # Keep it anyway so you see it on tables; it just won't have coordinates
                missing.append(icao)
                # Put a placeholder at PA center so it doesn't crash leaflet if used
                lat, lon = 40.9, -77.7
                name = f"{icao} (station metadata missing)"
            else:
                try:
                    lat = float(r.get("latitude"))
                    lon = float(r.get("longitude"))
                except Exception:
                    lat, lon = 40.9, -77.7
                name = (r.get("station_name") or icao).strip()

            regions_out[region_name].append({
                "code": code3,
                "icao": icao,
                "name": name,
                "lat": lat,
                "lon": lon
            })

            airports_out[code3] = {
                "icao": icao,
                "status": "OK",
                "flight_category": "UNK",
                "impact_reason": ""
            }

    out = {
        "generated_utc": now_utc_iso_z(),
        "regions": regions_out,
        "airports": airports_out
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
        f.write("\n")

    if missing:
        print("WARNING: Missing station metadata for:", ", ".join(missing), file=sys.stderr)

if __name__ == "__main__":
    main()
