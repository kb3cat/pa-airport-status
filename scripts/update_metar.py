#!/usr/bin/env python3
"""
update_metar.py
GitHub-pages-friendly builder/updater for docs/status.json

Source:
- IEM ASOS request (mesonet.agron.iastate.edu) for PA stations + raw METAR + lat/lon

Behavior:
- Builds FULL station list for Pennsylvania (ASOS/AWOS sites that report METAR)
- Regions: Western / Central / Eastern by longitude bands
- Preserves manual fields from existing docs/status.json:
    - status
    - impact_reason
- Computes flight_category from METAR (VFR/MVFR/IFR/LIFR/UNK)
- Stores:
    - metar_raw
    - metar_time_utc (from IEM "valid" timestamp)
- Writes docs/status.json
"""

import csv
import io
import json
import os
import re
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

STATUS_PATH = "docs/status.json"
UA = "PA-Airport-Status-GitHub/1.0"

# IEM ASOS/AWOS feed (CSV). We request lat/lon and the raw METAR.
# NOTE: IEM uses "station" (ICAO) + "name" + "lat"/"lon" + "valid" + "metar"
IEM_PA_CSV_URL = (
    "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
    "?data=all&state=PA&tz=Etc/UTC&format=csv&latlon=yes"
)

def now_utc_iso_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def fetch_text(url: str, timeout: int = 30) -> str:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")

def parse_csv(csv_text: str):
    # IEM CSV is standard header + rows
    return list(csv.DictReader(io.StringIO(csv_text)))

def as_float(x):
    try:
        return float(x)
    except Exception:
        return None

def region_from_lon(lon: float) -> str:
    # Rough PA split (adjust whenever)
    if lon <= -78.5:
        return "Western"
    if lon <= -76.5:
        return "Central"
    return "Eastern"

def code_from_icao(icao: str) -> str:
    i = (icao or "").strip().upper()
    if len(i) == 4 and i.startswith("K"):
        return i[1:]  # KMDT -> MDT
    return i

def load_existing():
    if not os.path.isfile(STATUS_PATH):
        return {}
    try:
        with open(STATUS_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

# ----------------------------
# METAR parsing (simple + robust)
# ----------------------------

VIS_RE = re.compile(r"^(?:(\d+)\s)?(\d+)?(?:/(\d+))?SM$")  # handles "10SM", "1SM", "1 1/2SM", "3/4SM"
CLOUD_RE = re.compile(r"^(FEW|SCT|BKN|OVC|VV)(\d{3})")

def parse_visibility_sm(tokens):
    # Prefer the first token that ends with SM and parse it
    for t in tokens:
        t = t.strip()
        if not t.endswith("SM"):
            continue
        m = VIS_RE.match(t)
        if not m:
            continue
        whole_with_space = m.group(1)
        whole = m.group(2)
        num = m.group(2)
        den = m.group(3)
        # Cases:
        # "10SM" => group2=10, group3=None
        # "3/4SM" => group2=3, group3=4
        # "1 1/2SM" => group1=1 , group2=1, group3=2  (because of regex structure)
        try:
            base = 0.0
            if whole_with_space:
                base += float(whole_with_space.strip())
            if den:
                base += float(num) / float(den)
            else:
                base += float(num)
            return base
        except Exception:
            continue
    return None

def parse_ceiling_ft(tokens):
    # Ceiling is lowest BKN/OVC/VV layer height (hundreds of feet)
    ceilings = []
    for t in tokens:
        m = CLOUD_RE.match(t.strip())
        if not m:
            continue
        kind = m.group(1)
        hhh = m.group(2)
        if kind in ("BKN", "OVC", "VV"):
            try:
                ceilings.append(int(hhh) * 100)
            except Exception:
                pass
    if not ceilings:
        return None
    return min(ceilings)

def flight_category_from_metar(raw: str) -> str:
    if not raw or not isinstance(raw, str):
        return "UNK"
    tokens = raw.split()

    vis = parse_visibility_sm(tokens)
    ceil = parse_ceiling_ft(tokens)

    # If we can't parse either, return UNK
    if vis is None and ceil is None:
        return "UNK"

    # Treat missing as very good for category checks
    vis_val = vis if vis is not None else 99.0
    ceil_val = ceil if ceil is not None else 99999

    # Standard thresholds
    if vis_val < 1.0 or ceil_val < 500:
        return "LIFR"
    if vis_val < 3.0 or ceil_val < 1000:
        return "IFR"
    if vis_val < 5.0 or ceil_val < 3000:
        return "MVFR"
    return "VFR"

def main():
    existing = load_existing()
    existing_airports = existing.get("airports", {}) if isinstance(existing.get("airports", {}), dict) else {}

    # Pull IEM station list + latest obs/metar
    try:
        csv_text = fetch_text(IEM_PA_CSV_URL)
    except (HTTPError, URLError) as e:
        raise SystemExit(f"Failed to fetch IEM ASOS feed: {e}")

    rows = parse_csv(csv_text)

    regions = {"Western": [], "Central": [], "Eastern": []}
    airports = {}

    # IEM CSV fields commonly include: station, name, valid, lon, lat, metar (and more)
    for r in rows:
        icao = (r.get("station") or "").strip().upper()
        if len(icao) != 4:
            continue
        lat = as_float(r.get("lat"))
        lon = as_float(r.get("lon"))
        if lat is None or lon is None:
            continue

        name = (r.get("name") or icao).strip()
        metar_raw = (r.get("metar") or "").strip()
        valid = (r.get("valid") or "").strip()  # e.g. 2026-01-27 05:10

        code = code_from_icao(icao)
        region = region_from_lon(lon)

        # De-dupe by code
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
            # preserve manual status + impact
            "status": prev.get("status", "OK"),
            "impact_reason": prev.get("impact_reason", ""),
            # update metar-driven fields
            "flight_category": flight_category_from_metar(metar_raw),
            "metar_raw": metar_raw,
            "metar_time_utc": valid
        }

    # Stable ordering
    for k in regions:
        regions[k].sort(key=lambda x: x["code"])

    out = {
        "generated_utc": now_utc_iso_z(),
        "regions": regions,
        "airports": airports
    }

    os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
    with open(STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
        f.write("\n")

    print(f"Wrote {STATUS_PATH} with {len(airports)} PA stations (IEM ASOS feed).")

if __name__ == "__main__":
    main()
