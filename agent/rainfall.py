"""Pull hourly rainfall for one NOAA station and clean it.

Rules (Process Outline, R8):
- Use only the regular hourly report for each hour (skip mid-hour SPECI reports).
- Rain amount comes from the report's P group (P0004 = 0.04 in; P0000 = trace = 0.00).
- Regular report with no P group = dry hour = 0.00 in.
- 'PNO' in the report (gauge out of service), 'P////' (amount not measured), or no regular
  report = MISSING. Never counted as 0.
- MISSING_DATA flag only when a missing hour is near rain or in the last 24 h (Option B).
"""
import csv
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

from config import DATA_LATE_HOURS, NWS_HEADERS, RAIN_CACHE, STORM_THRESHOLD_IN

P_GROUP = re.compile(r"\sP(\d{4})(?=\s|$)")
P_UNKNOWN = re.compile(r"\sP/{4}(?=\s|$)")     # P//// = precipitation amount not measured
P_GARBLED = re.compile(r"\sP(?!\d{4}(?:\s|$))(?=\S{0,3}\d)\S{4}(?=\s|$)")   # e.g. P00A4: unreadable amount
FIELDS = ["hour_end_utc", "rain_in", "status"]


# ---------- 1. Download ----------
AWC_METAR_URL = "https://aviationweather.gov/api/data/metar"
TIME_GROUP = re.compile(r"\b(\d{2})(\d{2})(\d{2})Z\b")


def report_time(group, now):
    """Turn a report's DDHHMMZ group (e.g. 091956Z) into a full UTC datetime.
    The report has no month or year, so use the most recent matching day."""
    day, hour, minute = int(group[0:2]), int(group[2:4]), int(group[4:6])
    candidate = now
    for _ in range(3):   # this month, or up to two months back
        try:
            ts = candidate.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
            if ts <= now + timedelta(hours=1):
                return ts
        except ValueError:
            pass       # day doesn't exist in this month (e.g. 31 Nov)
        candidate = (candidate.replace(day=1) - timedelta(days=1))
    return None


def reports_from_raw_text(text, now):
    """Raw METAR/SPECI lines -> [{'timestamp', 'rawMessage'}] for clean_hourly."""
    reports = []
    for line in text.splitlines():
        line = line.strip()
        match = TIME_GROUP.search(line)
        if not line or not match:
            continue
        ts = report_time(match.group(0)[:6], now)
        if ts:
            reports.append({"timestamp": ts.isoformat(), "rawMessage": line})
    return reports


def fetch_reports(station_id, hours=168):
    """Hourly (METAR) and extra (SPECI) reports from NOAA's Aviation Weather Center.
    Same ASOS reports as the NWS API, but complete; plain text, one line per report."""
    resp = requests.get(
        AWC_METAR_URL,
        headers=NWS_HEADERS,
        params={"ids": station_id, "hours": hours, "format": "raw"},
        timeout=30,
    )
    resp.raise_for_status()
    return reports_from_raw_text(resp.text, datetime.now(timezone.utc))


# ---------- 2. Clean ----------
def hour_end_of(ts):
    """A report at 19:53 closes the hour ending 20:00."""
    return (ts + timedelta(minutes=10)).replace(minute=0, second=0, microsecond=0)


def is_routine(raw, ts):
    """Regular hourly report: the line starts with METAR (extra reports start with SPECI)."""
    return raw.startswith("METAR")


def rain_from_report(raw):
    """Return (inches or None, status) from one regular report's text."""
    if " PNO" in raw or P_UNKNOWN.search(raw) or P_GARBLED.search(raw):
        return None, "missing"          # gauge out of service / amount not measured / unreadable
    match = P_GROUP.search(raw)
    if match:
        return int(match.group(1)) / 100, "ok"   # P0000 = trace = 0.00
    return 0.0, "dry"                   # no P group = no rain reported


def clean_hourly(reports, start, end):
    """One row per hour from start to end (UTC, hour-ending)."""
    routine = {}
    for p in reports:
        raw = (p.get("rawMessage") or "").strip()
        if not raw:
            continue
        ts = datetime.fromisoformat(p["timestamp"]).astimezone(timezone.utc)
        if is_routine(raw, ts):
            routine[hour_end_of(ts)] = raw     # one regular report per hour

    rows = []
    hour = start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while hour <= end:
        if hour in routine:
            inches, status = rain_from_report(routine[hour])
        elif hour > end - timedelta(hours=2):
            inches, status = None, "pending"   # report not published yet
        else:
            inches, status = None, "missing"
        rows.append({"hour_end_utc": hour, "rain_in": inches, "status": status})
        hour += timedelta(hours=1)
    return rows


# ---------- 3. Storm trigger ----------
def missing_matters(rows, now=None):
    """Option B (Alex, Nov 10): a missing hour counts only if it could hide a storm:
    it falls within 24 h of an hour with reported precipitation (including a trace),
    or it is within the last 24 h. Dry-weather gaps are ignored."""
    now = now or datetime.now(timezone.utc)
    rain_hours = [r["hour_end_utc"] for r in rows if r["status"] == "ok"]
    for r in rows:
        if r["status"] != "missing":
            continue
        t = r["hour_end_utc"]
        if now - t <= timedelta(hours=24):
            return True
        if any(abs(t - h) < timedelta(hours=24) for h in rain_hours):
            return True
    return False


def storm_trigger(rows, threshold=STORM_THRESHOLD_IN, now=None):
    """Return (T, max_24h_in, flags). T = first hour the rolling 24-h total reaches threshold.
    now: the time to judge DATA_LATE and MISSING_DATA against (default: the real current time;
    the demo passes the last refresh time so cached data is not flagged late)."""
    now = now or datetime.now(timezone.utc)
    trigger, max_24h, flags = None, 0.0, set()
    for i, row in enumerate(rows):
        window = rows[max(0, i - 23): i + 1]
        total = round(sum(r["rain_in"] or 0 for r in window), 2)
        max_24h = max(max_24h, total)
        if trigger is None and total >= threshold:
            trigger = row["hour_end_utc"]
    if missing_matters(rows, now):
        flags.add("MISSING_DATA")
    reported = [r["hour_end_utc"] for r in rows if r["status"] in ("ok", "dry")]
    if not reported or now - max(reported) > timedelta(hours=DATA_LATE_HOURS + 1):
        flags.add("DATA_LATE")
    return trigger, max_24h, sorted(flags)


# ---------- 4. Cache (keeps history beyond NWS's 7 days) ----------
def save_cache(station_id, rows):
    """Merge rows into data/rain_cache/<station>.csv. Newer data replaces older for the same hour."""
    RAIN_CACHE.mkdir(parents=True, exist_ok=True)
    path = RAIN_CACHE / f"{station_id}.csv"
    merged = {r["hour_end_utc"]: r for r in load_cache(station_id)}
    for r in rows:
        if r["status"] != "missing" or r["hour_end_utc"] not in merged:
            merged[r["hour_end_utc"]] = r
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for hour in sorted(merged):
            r = merged[hour]
            writer.writerow({"hour_end_utc": hour.isoformat(),
                             "rain_in": "" if r["rain_in"] is None else f"{r['rain_in']:.2f}",
                             "status": r["status"]})
    return path


def load_cache(station_id):
    """Read cached hourly rows for a station (empty list if none)."""
    path = RAIN_CACHE / f"{station_id}.csv"
    if not path.exists():
        return []
    rows = []
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            rows.append({"hour_end_utc": datetime.fromisoformat(r["hour_end_utc"]),
                         "rain_in": float(r["rain_in"]) if r["rain_in"] else None,
                         "status": r["status"]})
    return rows


# ---------- 5. One call that does everything ----------
def rain_for_station(station_id, hours=168):
    """Download, clean, cache. Returns (rows, trigger_time, max_24h_in, flags)."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    rows = clean_hourly(fetch_reports(station_id, hours), start, end)
    save_cache(station_id, rows)
    trigger, max_24h, flags = storm_trigger(rows)
    return rows, trigger, max_24h, flags


# ---------- Test from the terminal ----------
# uv run python -m agent.rainfall 45.68 -111.04
if __name__ == "__main__":
    from agent.stations import nearest_station

    lat, lon = float(sys.argv[1]), float(sys.argv[2])
    station, station_flags = nearest_station(lat, lon)
    if station is None:
        sys.exit("No NOAA station found for that location.")
    print(f"Nearest station: {station['station_id']} {station['name']} "
          f"({station['distance_mi']} mi) {station_flags}")

    rows, trigger, max_24h, flags = rain_for_station(station["station_id"])
    counts = {s: sum(r["status"] == s for r in rows) for s in ("ok", "dry", "missing")}
    print(f"Hours checked: {len(rows)}  rain hours: {counts['ok']}  "
          f"dry: {counts['dry']}  missing: {counts['missing']}")
    print(f"Max rolling 24-h rain: {max_24h:.2f} in")
    print(f"Storm trigger (0.25 in reached): {trigger or 'none in last 7 days'}")
    print(f"Flags: {flags + station_flags or 'none'}")
    print(f"Saved to data/rain_cache/{station['station_id']}.csv")
