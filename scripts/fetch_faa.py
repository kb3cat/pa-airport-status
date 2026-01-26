#!/usr/bin/env python3
import json, urllib.request, time
from datetime import datetime, timezone
from pathlib import Path

EVENT_URL = "https://nasstatus.faa.gov/api/airport-event-information"
STATUS_URL = "https://nasstatus.faa.gov/api/airport-status-information"

OUT_PATH = Path("docs/status.json")

AIRPORTS = {
  "Western": ["PIT","ERI","LBE","JST","DUJ"],
  "Central": ["MDT","CXY","SCE","IPT","AOO","BFD"],
  "Eastern": ["PHL","ABP","ABE","AVP","RDG","LNS","MPO"],
}

def fetch_json(url):
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                return json.loads(r.read())
        except:
            time.sleep(2)
    return {}

def main():
    event_data = fetch_json(EVENT_URL)
    status_data = fetch_json(STATUS_URL)

    closures = {}

    # FAA UI style events
    for ev in event_data.get("airportEvents", []):
        code = ev.get("airportId")
        etype = ev.get("eventType","").lower()
        reason = ev.get("title","") or ev.get("reason","")

        if code and "closure" in etype:
            closures[code] = reason

    airports_out = {}

    for region, codes in AIRPORTS.items():
        for code in codes:
            closed = code in closures

            airports_out[code] = {
                "code": code,
                "status": "CLOSED" if closed else "OK",
                "closed": closed,
                "closure_reason": closures.get(code,""),
                "events": []
            }

    payload = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "regions": {
            "Western":[{"code":c,"name":c} for c in AIRPORTS["Western"]],
            "Central":[{"code":c,"name":c} for c in AIRPORTS["Central"]],
            "Eastern":[{"code":c,"name":c} for c in AIRPORTS["Eastern"]],
        },
        "airports": airports_out,
        "source": "FAA airport-event-information + airport-status-information"
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2))

if __name__ == "__main__":
    main()
