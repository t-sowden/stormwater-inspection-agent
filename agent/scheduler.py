"""Inspection due dates under the EPA 2022 CGP. Plain Python, no AI.

Implements Process Outline Section 4, rules R1-R7 (signed off by Alex, Nov 8):
  R1  Option A: every 7 calendar days; if day 7 is not a working day, the last working day before it.
  R2  Option B: every 14 calendar days from the last inspection of any type (a storm inspection restarts the clock).
  R3  Impaired / Tier 2-3 waters: 7-day routine AND storm inspections.
  R4  Storm: T = hour the rolling 24-h total first reaches 0.25 in. Window = T to T + 24 h.
      Practical deadline = end of the last working hour inside the window.
  R5  Multi-day storm: inspect after the first qualifying day and after the last one (2 maximum).
  R6  Window entirely outside working hours: end of the next business day.
  R7  3 or fewer working hours left in the window: show both deadlines, flag INTERPRETATION_REQUIRED.
Federal holidays (observed dates) are non-working days unless the site works holidays.
Corrective-action rules (R9-R14) are added with the Draft Report tab.
"""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from config import (DEFAULT_WORK_DAYS, DEFAULT_WORK_END, DEFAULT_WORK_START,
                    INTERPRETATION_CUTOFF_HOURS, SITE_TZ, STORM_THRESHOLD_IN)

LOCAL = ZoneInfo(SITE_TZ)
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ---------- Federal holidays ----------
def _nth_weekday(year, month, weekday, n):
    """n-th weekday (0=Mon) of a month; n=-1 means the last one."""
    if n > 0:
        d = date(year, month, 1)
        d += timedelta(days=(weekday - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    d = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d):
    """Saturday holidays are observed Friday; Sunday holidays Monday."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def federal_holidays(year):
    """Observed US federal holidays for a year."""
    fixed = [date(year, 1, 1), date(year, 6, 19), date(year, 7, 4), date(year, 11, 11), date(year, 12, 25)]
    floating = [
        _nth_weekday(year, 1, 0, 3),    # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),    # Washington's Birthday
        _nth_weekday(year, 5, 0, -1),   # Memorial Day
        _nth_weekday(year, 9, 0, 1),    # Labor Day
        _nth_weekday(year, 10, 0, 2),   # Columbus Day
        _nth_weekday(year, 11, 3, 4),   # Thanksgiving
    ]
    return {_observed(d) for d in fixed} | set(floating)


# ---------- Site calendar ----------
def parse_work_days(text):
    """'Mon-Fri' or 'Mon,Tue,Sat' -> set of weekday numbers."""
    days = set()
    for part in str(text).replace(" ", "").split(","):
        if "-" in part:
            a, b = (DAY_NAMES.index(x[:3].title()) for x in part.split("-"))
            days.update(range(a, b + 1))
        elif part:
            days.add(DAY_NAMES.index(part[:3].title()))
    return days


class SiteCalendar:
    """When a site is open: working days, daily hours, and holiday handling."""

    def __init__(self, work_days=DEFAULT_WORK_DAYS, start=DEFAULT_WORK_START,
                 end=DEFAULT_WORK_END, works_holidays=False):
        self.days = parse_work_days(work_days)
        self.start = time.fromisoformat(start)
        self.end = time.fromisoformat(end)
        self.works_holidays = works_holidays

    def is_workday(self, d):
        if d.weekday() not in self.days:
            return False
        return self.works_holidays or d not in federal_holidays(d.year)

    def bounds(self, d):
        return (datetime.combine(d, self.start, LOCAL), datetime.combine(d, self.end, LOCAL))

    def working_hours(self, a, b):
        """Working hours between two local datetimes."""
        total, d = 0.0, a.date()
        while d <= b.date():
            if self.is_workday(d):
                s, e = self.bounds(d)
                overlap = (min(e, b) - max(s, a)).total_seconds()
                total += max(0.0, overlap) / 3600
            d += timedelta(days=1)
        return total

    def last_work_end_in(self, a, b):
        """End of the last working hour inside [a, b] (None if no working time)."""
        d = b.date()
        while d >= a.date():
            if self.is_workday(d):
                s, e = self.bounds(d)
                if s < b and e > a:
                    return min(e, b)
            d -= timedelta(days=1)
        return None

    def next_business_day_end(self, d):
        """End of working hours on the first working day after date d."""
        d += timedelta(days=1)
        while not self.is_workday(d):
            d += timedelta(days=1)
        return self.bounds(d)[1]

    def last_workday_on_or_before(self, d):
        while not self.is_workday(d):
            d -= timedelta(days=1)
        return d


def calendar_for(site):
    """Build a SiteCalendar from a sites.csv row (blank cells use the defaults)."""
    def val(key, default):
        v = site.get(key)
        return default if v is None or str(v).strip() in ("", "nan") else str(v).strip()
    return SiteCalendar(val("work_days", DEFAULT_WORK_DAYS), val("work_start", DEFAULT_WORK_START),
                        val("work_end", DEFAULT_WORK_END), val("works_holidays", "no").lower() == "yes")


# ---------- Deadlines ----------
def routine_due(last_inspection, days, cal):
    """R1/R2: end of working hours on day N, moved back to the last working day if needed."""
    target = (last_inspection + timedelta(days=days)).date()
    return cal.bounds(cal.last_workday_on_or_before(target))[1]


def storm_deadline(trigger, cal):
    """R4/R6/R7 for one trigger time. Returns (due, alternate_due, rule, flags)."""
    window_end = trigger + timedelta(hours=24)
    hours = cal.working_hours(trigger, window_end)
    if hours == 0:
        return cal.next_business_day_end(trigger.date()), None, "R6", []
    literal = cal.last_work_end_in(trigger, window_end)
    if hours <= INTERPRETATION_CUTOFF_HOURS:
        return literal, cal.next_business_day_end(trigger.date()), "R7", ["INTERPRETATION_REQUIRED"]
    return literal, None, "R4", []


def storm_triggers(hourly, after, threshold=STORM_THRESHOLD_IN):
    """R4/R5: trigger times (local) after the last inspection; at most 2 per storm event.

    hourly: rows with 'hour_end_utc' (UTC datetime) and 'rain_in' (None = missing).
    Event = consecutive hours whose rolling 24-h total is >= threshold.
    Inside an event, a local calendar day 'qualifies' when its own rain total >= threshold.
    Inspections: first trigger, plus the time the last qualifying day reached the threshold.
    """
    rows = [r for r in hourly if r["hour_end_utc"] > after]
    triggers, event = [], None
    for i, r in enumerate(rows):
        window = rows[max(0, i - 23): i + 1]
        total = round(sum(x["rain_in"] or 0 for x in window), 2)
        if total >= threshold:
            if event is None:
                event = {"start": r["hour_end_utc"], "rows": []}
            event["rows"].append(r)
        elif event is not None:
            triggers += _event_triggers(event, threshold)
            event = None
    if event is not None:
        triggers += _event_triggers(event, threshold)
    return triggers


def _event_triggers(event, threshold):
    first = event["start"].astimezone(LOCAL)
    day_totals, day_reached = {}, {}
    for r in event["rows"]:
        local = r["hour_end_utc"].astimezone(LOCAL)
        d = local.date()
        day_totals[d] = round(day_totals.get(d, 0) + (r["rain_in"] or 0), 2)
        if day_totals[d] >= threshold and d not in day_reached:
            day_reached[d] = local
    qualifying = sorted(day_reached)
    out = [(first, "first day")]
    if len(qualifying) >= 2 and qualifying[-1] > first.date():
        out.append((day_reached[qualifying[-1]], "last day (R5)"))
    return out


def site_schedule(site, hourly, now=None, data_flags=()):
    """All open deadlines for one site, earliest first.

    site: dict from sites.csv. hourly: cleaned rainfall rows for the site's station.
    Returns a list of dicts: kind, due, alt_due, rule, trigger, flags.
    """
    now = now or datetime.now(timezone.utc)
    cal = calendar_for(site)
    last = datetime.fromisoformat(str(site["last_inspection"]).strip()).replace(tzinfo=LOCAL)
    option = str(site.get("frequency_option", "B")).strip().upper()
    impaired = str(site.get("impaired_water", "no")).strip().lower() == "yes"

    items = []
    routine_days = 7 if (option == "A" or impaired) else 14
    rule = "R3" if impaired else ("R1" if option == "A" else "R2")
    items.append({"kind": "Routine", "due": routine_due(last, routine_days, cal), "alt_due": None,
                  "rule": rule, "trigger": None, "flags": []})

    if option == "B" or impaired:   # storm inspections apply
        for trigger, label in storm_triggers(hourly, last):
            due, alt, srule, flags = storm_deadline(trigger, cal)
            items.append({"kind": f"Storm ({label})", "due": due, "alt_due": alt,
                          "rule": srule if label == "first day" else "R5", "trigger": trigger,
                          "flags": flags})
        # R2: a storm inspection restarts the 14-day clock, so the routine date never needs
        # to move here; the inspector logs the inspection and last_inspection updates.

    for it in items:
        if it["due"] < now.astimezone(LOCAL):
            it["flags"] = it["flags"] + ["OVERDUE"]
    return sorted(items, key=lambda it: it["due"])
