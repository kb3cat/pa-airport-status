#!/usr/bin/env python3
import json
import re
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

STATUS_PATH = "docs/status.json"
UA = "PA-Airport-Status-GitHub/1.0"

def now_utc_iso_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def fetch_text(url: str, timeout: int = 12) -> str:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")

def parse_metar_time_utc(metar: str) -> str:
    m = re.search(r"\b(\d{2})(\d{2})(\d{2})Z\b", metar)
    if not m:
        return ""
    dd, hh, mm = m.group(1), m.group(2), m.group(3)
    return f"{dd} {hh}:{mm}Z"

def parse_visibility_sm(metar: str):
    m = re.search(r"\b(\d+)\s+(\d+)/(\d+)SM\b", metar)
    if m:
        return float(m.group(1)) + float(m.group(2)) / float(m.group(3))
    m = re.search(r"\b(\d+)/(\d+)SM\b", metar)
    if m:
        return float(m.group(1)) / float(m.group(2))
    m = re.search(r"\b(\d+)SM\b", metar)
    if m:
        return float(m.group(1))
    return None

def parse_ceiling_ft_agl(metar: str):
    layers = re.findall(r"\b(VV|BKN|OVC)(\d{3})\b", metar)
    vals = []
    for _, h in layers:
        try:
            vals.append(int(h) * 100)
        except ValueError:
            pass
    return min(vals) if vals else None

def flight_category_from_metar(metar: str):
    vis = parse_visibility_sm(metar)
    ceil = parse_ceiling_ft_agl(metar)

    if vis is None and ceil is None:
        return ("UNK", "")

    if (ceil is not None and ceil < 500) or (vis is not None and vis < 1.0):
        parts = []
        if ceil is not None: parts.append(f"ceiling {ceil}ft")
        if vis is not None: parts.append(f"vis {vis:g}SM")
        return ("LIFR", ", ".join(parts))

    if (ceil is not None and 500 <= ceil < 1000) or (vis is not None and 1.0 <= vis < 3.0):
        parts = []
        if ceil is not None: parts.append(f"ceiling {ceil}ft")
        if vis is not None: parts.append(f"vis {vis:g}SM")
        return ("IFR", ", ".join(parts))

    if (ceil is not None and 1000 <= ceil < 3000) or (vis is not None and 3.0 <= vis <= 5.0):
        parts = []
        if ceil is not None: parts.append(f"ceiling {ceil}ft")
        if vis is not None: parts.append(f"vis {vis:g}SM")
        return ("MVFR", ", ".join(parts))

    return ("VFR", "")

def status_from_flight_cat(cat: str) -> str:
    c = (cat or "UNK").upper()
    if c in ("MVFR", "IFR", "LIFR"):
        return "IMPACT"
    if c == "UNK":
        return "OK"
    return "OK"

def main():
    try:
        with open(STATUS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {STATUS_PATH} not found.", file=sys.stderr)
        sys.exit(2)

    airports = data.get("airports", {})
    if not isinstance(airports, dict) or not airports:
        print("ERROR: docs/status.json missing airports object or it's empty.", file=sys.stderr)
        sys.exit(3)

    updated_utc = now_utc_iso_z()

    for code3 in sorted(airports.keys()):
        stobj = airports.get(code3) or {}
        icao = (stobj.get("icao") or "").strip().upper()
        if not icao:
            # Fallback: assume K + 3-letter
            icao = "K" + code3.upper()

        url = f"https://aviationweather.gov/api/data/metar?ids={icao}&format=raw&hours=2&taf=false"
        try:
            raw = fetch_text(url).strip()
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            metar = lines[0] if lines else ""

            if not metar:
                airports[code3].update({
                    "status": "CLOSED",
                    "flight_category": "UNK",
                    "impact_reason": "No METAR returned",
                    "metar_raw": "",
                    "metar_time_utc": "",
                    "updated_utc": updated_utc
                })
                continue

            fc, fc_reason = flight_category_from_metar(metar)
            status = status_from_flight_cat(fc)

            impact_reason = ""
            if status == "IMPACT":
                impact_reason = f"{fc}: {fc_reason}" if fc_reason else fc

            airports[code3].update({
                "icao": icao,
                "status": status,
                "flight_category": fc,
                "impact_reason": impact_reason,
                "metar_raw": metar,
                "metar_time_utc": parse_metar_time_utc(metar),
                "updated_utc": updated_utc
            })

        except (HTTPError, URLError):
            airports[code3].update({
                "icao": icao,
                "status": "CLOSED",
                "flight_category": "UNK",
                "impact_reason": "METAR fetch error",
                "metar_raw": "",
                "metar_time_utc": "",
                "updated_utc": updated_utc
            })

    data["generated_utc"] = updated_utc
    data["airports"] = airports

    with open(STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

if __name__ == "__main__":
    main()
