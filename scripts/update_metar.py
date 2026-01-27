#!/usr/bin/env python3
import json
import os
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

STATUS_JSON_PATH = os.environ.get("STATUS_JSON_PATH", "status.json")
OUTPUT_JSON_PATH = os.environ.get("OUTPUT_JSON_PATH", "status.json")
SLEEP_MS = int(os.environ.get("SLEEP_BETWEEN_REQUESTS_MS", "150"))

TIMEOUT_SECONDS = 10

def utc_now_string():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

def code_to_icao(code: str) -> str:
    c = (code or "").strip().upper()
    if len(c) == 4:
        return c
    if len(c) == 3:
        return "K" + c
    return c

def fetch_metar_raw(icao: str) -> str | None:
    url = f"https://aviationweather.gov/api/data/metar?ids={icao}&format=raw&hours=2&taf=false"
    req = Request(url, headers={
        "User-Agent": "pa-airport-status/1.0 (github actions)",
        "Accept": "text/plain",
    })
    try:
        with urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8", errors="replace").strip()
            if not body:
                return None
            low = body.lower()
            if "<html" in low or "<!doctype" in low:
                return None
            return body
    except (HTTPError, URLError, TimeoutError):
        return None

def impact_reason_from_entry(status: str, flight_category: str, metar_raw: str | None) -> tuple[str, str]:
    """
    Returns (impact_reason, impact_detail)
    """
    s = (status or "OK").strip().upper()
    fc = (flight_category or "UNK").strip().upper()
    met = (metar_raw or "").upper()

    if s == "CLOSED":
        return ("Airport closed", "Status CLOSED")
    if s != "IMPACT":
        return ("", "")

    # Primary: flight rules
    if fc in ("LIFR", "IFR", "MVFR"):
        return (f"Flight rules {fc}", "Lower ceilings/visibility than VFR")

    # Secondary: quick METAR keyword hints (lightweight but useful)
    wx = []
    for token, label in [
        (" +SN", "heavy snow"),
        (" SN", "snow"),
        (" -SN", "light snow"),
        (" FZRA", "freezing rain"),
        (" RA", "rain"),
        (" TS", "thunderstorms"),
        (" FG", "fog"),
        (" BLSN", "blowing snow"),
        (" BR", "mist"),
    ]:
        if token.strip() in met:
            wx.append(label)
            break

    if wx:
        return ("Weather impacting operations", f"METAR indicates {wx[0]}")

    # Fallback
    return ("Operational impact", "Status IMPACT (reason not classified)")

def main():
    with open(STATUS_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    airports = data.get("airports")
    if not isinstance(airports, dict) or not airports:
        raise SystemExit("status.json is missing a non-empty 'airports' object.")

    fetched = 0
    failed = 0

    for code, entry in airports.items():
        if not isinstance(entry, dict):
            continue

        icao = code_to_icao(code)
        metar = fetch_metar_raw(icao)

        entry["metar_icao"] = icao
        entry["metar_ts"] = int(time.time())

        if metar:
            entry["metar_raw"] = metar
            fetched += 1
        else:
            # Keep existing metar_raw if it exists
            failed += 1

        # Compute/refresh impact reason (works even if metar fetch failed)
        status = (entry.get("status") or "OK")
        fc = (entry.get("flight_category") or "UNK")
        met_txt = entry.get("metar_raw") or ""

        reason, detail = impact_reason_from_entry(status, fc, met_txt)
        if reason:
            entry["impact_reason"] = reason
        else:
            entry.pop("impact_reason", None)

        if detail:
            entry["impact_detail"] = detail
        else:
            entry.pop("impact_detail", None)

        time.sleep(max(0, SLEEP_MS) / 1000.0)

    data["generated_utc"] = utc_now_string()

    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Done. METAR fetched: {fetched}  METAR failed: {failed}  Wrote: {OUTPUT_JSON_PATH}")

if __name__ == "__main__":
    main()
