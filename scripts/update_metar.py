#!/usr/bin/env python3
import csv
import io
import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen

STATUS_PATH = "docs/status.json"
UA = "PA-Airport-Status-GitHub/1.0"

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

def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def main():
    with open(STATUS_PATH, "r", encoding="utf-8") as f:
        d = json.load(f)

    airports = d.get("airports", {})
    if not isinstance(airports, dict) or not airports:
        raise SystemExit("status.json has no airports object.")

    icaos = []
    for code, rec in airports.items():
        icao = (rec.get("icao") or "").strip().upper()
        if len(icao) == 4:
            icaos.append(icao)

    icaos = sorted(set(icaos))
    if not icaos:
        raise SystemExit("No ICAO stations found to query.")

    metar_map = {}

    for part in chunks(icaos, 60):
        station_string = ",".join(part)
        url = (
            "https://aviationweather.gov/adds/dataserver_current/httpparam"
            "?dataSource=metars&requestType=retrieve&format=csv"
            f"&stationString={station_string}"
            "&hoursBeforeNow=2"
            "&mostRecentForEachStation=true"
        )
        text = fetch_text(url)
        rows = parse_csv_strip_comments(text)

        for r in rows:
            sid = (r.get("station_id") or "").strip().upper()
            if len(sid) != 4:
                continue
            metar_map[sid] = {
                "flight_category": (r.get("flight_category") or "UNK").strip().upper(),
                "raw_text": (r.get("raw_text") or "").strip(),
                "observation_time": (r.get("observation_time") or "").strip(),
            }

    for code, rec in airports.items():
        icao = (rec.get("icao") or "").strip().upper()
        if len(icao) != 4:
            continue

        m = metar_map.get(icao)
        if not m:
            if not rec.get("flight_category"):
                rec["flight_category"] = "UNK"
            continue

        fc = m["flight_category"] or "UNK"
        if fc not in ("VFR", "MVFR", "IFR", "LIFR"):
            fc = "UNK"

        rec["flight_category"] = fc
        rec["metar_raw"] = m["raw_text"]
        rec["metar_time_utc"] = m["observation_time"]

    d["generated_utc"] = now_utc_iso_z()

    with open(STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
        f.write("\n")

    print(f"Updated METARs for {len(metar_map)} stations into {STATUS_PATH}")

if __name__ == "__main__":
    main()
