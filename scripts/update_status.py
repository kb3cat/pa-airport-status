#!/usr/bin/env python3
import json
import re
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

STATUS_PATH = "docs/status.json"
UA = "PA-Airport-Status-GitHub/1.0"

def now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

def fetch_text(url: str, timeout: int = 12) -> str:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")

def parse_metar_time_utc(metar: str) -> str:
    """
    Pulls the DDHHMMZ group from METAR and returns as 'DD HH:MMZ' (UTC day-of-month only).
    We keep it simple for display.
    """
    m = re.search(r"\b(\d{2})(\d{2})(\d{2})Z\b", metar)
    if not m:
        return ""
    dd, hh, mm = m.group(1), m.group(2), m.group(3)
    return f"{dd} {hh}:{mm}Z"

def parse_visibility_sm(metar: str):
    """
    Returns visibility in statute miles (float) if present, else None.
    Handles '10SM', '1/2SM', '2 1/2SM'.
    """
    # e.g. "2 1/2SM"
    m = re.search(r"\b(\d+)\s+(\d+)/(\d+)SM\b", metar)
    if m:
        whole = float(m.group(1))
        num = float(m.group(2))
        den = float(m.group(3))
        return whole + (num / den)

    # e.g. "1/2SM"
    m = re.search(r"\b(\d+)/(\d+)SM\b", metar)
    if m:
        return float(m.group(1)) / float(m.group(2))

    # e.g. "10SM"
    m = re.search(r"\b(\d+)SM\b", metar)
    if m:
        return float(m.group(1))

    return None

def parse_ceiling_ft_agl(metar: str):
    """
    Returns the lowest BKN/OVC/VV layer base in feet AGL, else None.
    """
    # VV###, BKN###, OVC### where ### is hundreds of feet
    layers = re.findall(r"\b(VV|BKN|OVC)(\d{3})\b", metar)
    if not layers:
        return None
    vals = []
    for _, h in layers:
        try:
            vals.append(int(h) * 100)
        except ValueError:
            pass
    return min(vals) if vals else None

def flight_category_from_metar(metar: str) -> (str, str):
    """
    Computes VFR/MVFR/IFR/LIFR using standard thresholds.
    Returns (category, reason).
    """
    vis = parse_visibility_sm(metar)
    ceil = parse_ceiling_ft_agl(metar)

    # If we have neither, we can't compute reliably
    if vis is None and ceil is None:
        return ("UNK", "")

    # LIFR: ceiling < 500 OR visibility < 1
    if (ceil is not None and ceil < 500) or (vis is not None and vis < 1.0):
        r = []
        if ceil is not None: r.append(f"ceiling {ceil}ft")
        if vis is not None: r.append(f"vis {vis:g}SM")
        return ("LIFR", ", ".join(r))

    # IFR: ceiling 500–<1000 OR visibility 1–<3
    if (ceil is not None and 500 <= ceil < 1000) or (vis is not None and 1.0 <= vis < 3.0):
        r = []
        if ceil is not None: r.append(f"ceiling {ceil}ft")
        if vis is not None: r.append(f"vis {vis:g}SM")
        return ("IFR", ", ".join(r))

    # MVFR: ceiling 1000–<3000 OR visibility 3–<=5
    if (ceil is not None and 1000 <= ceil < 3000) or (vis is not None and 3.0 <= vis <= 5.0):
        r = []
        if ceil is not None: r.append(f"ceiling {ceil}ft")
        if vis is not None: r.append(f"vis {vis:g}SM")
        return ("MVFR", ", ".join(r))

    # VFR: ceiling > 3000 AND visibility > 5 (or missing counterpart but the other is good)
    return ("VFR", "")

def status_from_flight_cat(cat: str) -> str:
    c = (cat or "UNK").upper()
    if c in ("IFR", "LIFR", "MVFR"):
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
    updated_utc = now_utc_str()

    for code in sorted(airports.keys()):
        # Direct AviationWeather raw METAR
        url = f"https://aviationweather.gov/api/data/metar?ids={code}&format=raw&hours=2&taf=false"
        try:
            raw = fetch_text(url).strip()

            if not raw:
                airports[code]["status"] = "CLOSED"
                airports[code]["flight_category"] = "UNK"
                airports[code]["impact_reason"] = "no METAR"
                airports[code]["metar_raw"] = ""
                airports[code]["metar_time_utc"] = ""
                airports[code]["updated_utc"] = updated_utc
                continue

            # Some endpoints can return multiple lines; keep the first non-empty
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            metar = lines[0] if lines else raw

            fc, fc_reason = flight_category_from_metar(metar)
            st = status_from_flight_cat(fc)

            airports[code]["flight_category"] = fc
            airports[code]["status"] = st
            airports[code]["impact_reason"] = (f"{fc}: {fc_reason}" if fc_reason and st == "IMPACT" else ("Flight rules degraded" if st == "IMPACT" else ""))
            airports[code]["metar_raw"] = metar
            airports[code]["metar_time_utc"] = parse_metar_time_utc(metar)
            airports[code]["updated_utc"] = updated_utc

        except (HTTPError, URLError) as e:
            airports[code]["status"] = "CLOSED"
            airports[code]["flight_category"] = "UNK"
            airports[code]["impact_reason"] = "METAR fetch error"
            airports[code]["metar_raw"] = ""
            airports[code]["metar_time_utc"] = ""
            airports[code]["updated_utc"] = updated_utc

    data["generated_utc"] = updated_utc
    data["airports"] = airports

    with open(STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=False)
        f.write("\n")

if __name__ == "__main__":
    main()
