"""Scheduler tests from Process Outline Sections 4 and 6. Run: uv run --with pytest pytest"""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from agent.rainfall import missing_matters
from agent.scheduler import federal_holidays, site_schedule
from config import SITE_TZ

MT = ZoneInfo(SITE_TZ)          # site local time zone from config.py
NOW = datetime(2026, 12, 31, tzinfo=timezone.utc)          # far future: nothing overdue unless tested


def local(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=MT)


def hourly(rain, start, end, missing=()):
    """Hourly rows from start to end (local). rain = {local hour_end: inches}."""
    rows, t = [], start
    while t <= end:
        if t in missing:
            rows.append({"hour_end_utc": t.astimezone(timezone.utc), "rain_in": None, "status": "missing"})
        else:
            inches = rain.get(t, 0.0)
            rows.append({"hour_end_utc": t.astimezone(timezone.utc), "rain_in": inches,
                         "status": "ok" if t in rain else "dry"})
        t += timedelta(hours=1)
    return rows


def site(option="B", impaired="no", last="2026-11-09 08:00", **kw):
    s = {"site_id": "T1", "frequency_option": option, "impaired_water": impaired, "last_inspection": last}
    s.update(kw)
    return s


def storms(items):
    return [i for i in items if i["kind"].startswith("Storm")]


def week(rain, missing=(), start=local(2026, 11, 9, 9), end=local(2026, 11, 25, 0)):
    return hourly(rain, start, end, missing)


# ---------- Storm trigger (R4) ----------
def test_030_in_over_6_hours_due_24h_after_threshold_hour():
    rain = {local(2026, 11, 16, h): 0.05 for h in range(9, 15)}          # 0.30 in, 0.25 reached 13:00
    s = storms(site_schedule(site(), week(rain), NOW))
    assert len(s) == 1
    assert s[0]["trigger"] == local(2026, 11, 16, 13)
    assert s[0]["due"] == local(2026, 11, 17, 13)                      # not "storm end"


def test_024_in_no_trigger():
    rain = {local(2026, 11, 16, h): 0.04 for h in range(9, 15)}          # 0.24 in
    assert storms(site_schedule(site(), week(rain), NOW)) == []


def test_rolling_window_across_midnight():
    rain = {local(2026, 11, 16, 23): 0.14, local(2026, 11, 17, 1): 0.13}
    s = storms(site_schedule(site(), week(rain), NOW))
    assert s[0]["trigger"] == local(2026, 11, 17, 1)
    assert s[0]["due"] == local(2026, 11, 17, 17)                      # end of last working hour in window


# ---------- Weekends, Friday afternoon, holidays (R6, R7) ----------
def test_saturday_storm_due_end_of_monday():
    rain = {local(2026, 11, 14, 10): 0.30}
    s = storms(site_schedule(site(), week(rain), NOW))
    assert s[0]["rule"] == "R6"
    assert s[0]["due"] == local(2026, 11, 16, 17)


def test_friday_1400_shows_both_deadlines_and_flags():
    rain = {local(2026, 11, 20, 14): 0.30}
    s = storms(site_schedule(site(), week(rain), NOW))
    assert s[0]["rule"] == "R7"
    assert s[0]["due"] == local(2026, 11, 20, 17)
    assert s[0]["alt_due"] == local(2026, 11, 23, 17)
    assert "INTERPRETATION_REQUIRED" in s[0]["flags"]


def test_saturday_before_federal_monday_holiday_due_tuesday():
    rows = hourly({local(2026, 10, 10, 10): 0.30}, local(2026, 10, 5, 9), local(2026, 10, 16, 0))
    s = storms(site_schedule(site(last="2026-10-05 08:00"), rows, NOW))
    assert s[0]["due"] == local(2026, 10, 13, 17)                      # Columbus Day Mon Oct 12


def test_site_that_works_holidays_due_monday():
    rows = hourly({local(2026, 10, 10, 10): 0.30}, local(2026, 10, 5, 9), local(2026, 10, 16, 0))
    s = storms(site_schedule(site(last="2026-10-05 08:00", works_holidays="yes"), rows, NOW))
    assert s[0]["due"] == local(2026, 10, 12, 17)


# ---------- Multi-day storm (R5) ----------
def test_three_day_storm_two_inspections_not_three():
    rain = {local(2026, 11, 16, 10): 0.30, local(2026, 11, 17, 10): 0.25, local(2026, 11, 18, 10): 0.10}
    s = storms(site_schedule(site(), week(rain), NOW))
    assert [i["trigger"] for i in s] == [local(2026, 11, 16, 10), local(2026, 11, 17, 10)]


# ---------- Routine frequency (R1, R2, R3) ----------
def test_option_a_day7_on_sunday_moves_to_friday():
    items = site_schedule(site(option="A", last="2026-11-08 10:00"), week({}), NOW)
    assert items[0]["kind"] == "Routine" and items[0]["due"] == local(2026, 11, 13, 17)


def test_option_b_routine_is_14_days():
    items = site_schedule(site(last="2026-11-09 08:00"), week({}), NOW)
    assert items[0]["due"] == local(2026, 11, 23, 17)


def test_option_a_ignores_storms():
    rain = {local(2026, 11, 16, 10): 0.50}
    assert storms(site_schedule(site(option="A"), week(rain), NOW)) == []


def test_impaired_water_is_7_day_plus_storm():
    rain = {local(2026, 11, 16, 10): 0.50}
    items = site_schedule(site(impaired="yes", last="2026-11-09 08:00"), week(rain), NOW)
    routine = [i for i in items if i["kind"] == "Routine"][0]
    assert routine["rule"] == "R3" and routine["due"] == local(2026, 11, 16, 17)
    assert len(storms(items)) == 1


def test_rain_before_last_inspection_ignored():
    rain = {local(2026, 11, 10, 10): 0.50}
    assert storms(site_schedule(site(last="2026-11-12 08:00"), week(rain), NOW)) == []


def test_overdue_flag():
    rain = {local(2026, 11, 16, 10): 0.50}
    now = local(2026, 11, 18, 12).astimezone(timezone.utc)
    s = storms(site_schedule(site(), week(rain), now))
    assert "OVERDUE" in s[0]["flags"]


# ---------- Holidays ----------
def test_holidays_2026():
    h = federal_holidays(2026)
    assert date(2026, 11, 26) in h          # Thanksgiving
    assert date(2026, 7, 3) in h            # July 4 is a Saturday, observed Friday
    assert date(2026, 11, 11) in h          # Veterans Day


# ---------- Missing data, Option B ----------
NOW_MD = local(2026, 11, 24, 12).astimezone(timezone.utc)


def test_missing_hour_in_dry_week_not_flagged():
    rows = week({}, missing={local(2026, 11, 12, 3)})
    assert missing_matters(rows, NOW_MD) is False


def test_missing_hour_near_rain_flagged():
    rows = week({local(2026, 11, 12, 6): 0.10}, missing={local(2026, 11, 12, 3)})
    assert missing_matters(rows, NOW_MD) is True


def test_missing_hour_in_last_24h_flagged():
    rows = week({}, missing={local(2026, 11, 24, 2)})
    assert missing_matters(rows, NOW_MD) is True
