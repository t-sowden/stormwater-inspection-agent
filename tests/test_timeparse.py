"""Every time field reads the same whether written the app's way or the way Excel re-saves it."""
from datetime import datetime, time, timezone

import pytest

from agent import corrective, records, site_admin, workbook
from agent.scheduler import calendar_for, site_schedule
from agent.timeparse import parse_clock, parse_local_datetime
from book_helpers import raw_book
from test_no_inspection import app_helpers, new_site, stations

NOW = datetime(2026, 12, 31, tzinfo=timezone.utc)


# ---------- The two helpers ----------
@pytest.mark.parametrize("text, expected", [
    ("7:00", time(7, 0)), ("07:00", time(7, 0)), ("17:30", time(17, 30)), ("07:00:00", time(7, 0)),
    ("7:00 AM", time(7, 0)), ("5:00 pm", time(17, 0)), ("5:00PM", time(17, 0)), ("12:00 AM", time(0, 0)),
    ("7:00:00 AM", time(7, 0)), (" 7:00 ", time(7, 0)),
])
def test_parse_clock(text, expected):
    assert parse_clock(text) == expected


@pytest.mark.parametrize("bad", ["7", "7am", "25:00", "7:5", "7:60", "", "13:00 PM", "noon"])
def test_parse_clock_rejects_with_value(bad):
    with pytest.raises(ValueError, match=f"unreadable time '{bad}'"):
        parse_clock(bad)


@pytest.mark.parametrize("text", ["2026-11-09 09:00", "2026-11-09 09:00:00", "11/9/2026 9:00",
                                  "11/9/2026 9:00 AM", "11/09/2026 09:00"])
def test_parse_local_datetime_same_moment(text):
    assert parse_local_datetime(text) == datetime(2026, 11, 9, 9, 0)


def test_parse_local_datetime_midnight_and_error():
    assert parse_local_datetime("11/9/2026") == datetime(2026, 11, 9)
    with pytest.raises(ValueError, match=r"last_inspection: unreadable time '9 Nov 2026'"):
        parse_local_datetime("9 Nov 2026", "last_inspection")


# ---------- sites sheet: work_start / work_end ----------
def test_work_hours_both_formats_same_schedule():
    base = {"site_id": "T1", "frequency_option": "A", "impaired_water": "no", "last_inspection": "2026-11-09 08:00"}
    iso = site_schedule({**base, "work_start": "07:00", "work_end": "17:00"}, [], NOW)
    excel = site_schedule({**base, "work_start": "7:00", "work_end": "17:00"}, [], NOW)
    ampm = site_schedule({**base, "work_start": "7:00 AM", "work_end": "5:00 PM"}, [], NOW)
    assert iso == excel == ampm
    assert iso[0]["due"].hour == 17
    cal = calendar_for({"work_start": "7:00", "work_end": "15:00"})
    assert (cal.start, cal.end) == (time(7, 0), time(15, 0))


def test_bad_work_hours_name_file_and_field():
    with pytest.raises(ValueError, match=r"sheet sites work_start: unreadable time '7h'"):
        calendar_for({"work_start": "7h"})
    with pytest.raises(ValueError, match=r"sheet sites work_end: unreadable time '25:00'"):
        calendar_for({"work_end": "25:00"})


# ---------- sites sheet: last_inspection ----------
def test_sites_last_inspection_both_formats(monkeypatch):
    monkeypatch.setattr(records, "inspections", lambda site_id=None: [])
    base = {"site_id": "T1", "frequency_option": "B", "impaired_water": "no"}
    iso = records.last_inspection("T1", "2026-11-09 09:00")
    us = records.last_inspection("T1", "11/9/2026 9:00")
    assert site_schedule({**base, "last_inspection": iso}, [], NOW) == \
        site_schedule({**base, "last_inspection": us}, [], NOW)


# ---------- inspections sheet: inspected_at (real Excel date-times, ISO text, US text) ----------
@pytest.mark.parametrize("a, b", [
    ("2026-11-09 17:00", "2026-11-10 08:00"),
    ("11/9/2026 17:00", "11/10/2026 8:00"),                  # '11/10' < '11/9' as text
    ("11/9/2026 5:00 PM", "2026-11-10 08:00"),
    (datetime(2026, 11, 9, 17, 0), datetime(2026, 11, 10, 8, 0)),
    (datetime(2026, 11, 9, 17, 0), "11/10/2026 8:00 AM"),
])
def test_inspected_at_both_formats(tmp_path, monkeypatch, a, b):
    book = raw_book(tmp_path / "INSPECTOR_RECORDS.xlsx", inspections=(
        workbook.SHEETS["inspections"], [["I1", "T01", b, "routine", "A"], ["I2", "T01", a, "storm", "A"]]))
    monkeypatch.setattr(records, "RECORDS_FILE", book)
    assert records.last_inspection("T01") == "2026-11-10 08:00"


# ---------- deficiencies sheet: found_at / closed_at ----------
def deficiencies_book(tmp_path, found, closed):
    return raw_book(tmp_path / "INSPECTOR_RECORDS.xlsx", deficiencies=(workbook.SHEETS["deficiencies"], [
        ["D1", "T01", "I1", "SF-1", found, "Sediment", "routine_maintenance", "open", None],
        ["D2", "T01", "I1", "IP-2", found, "Torn bag", "corrective_no_new_control", "closed", closed]]))


def test_found_and_closed_at_both_formats(tmp_path, monkeypatch):
    site = {"site_id": "T01", "work_days": "Mon-Fri", "work_start": "07:00", "work_end": "17:00"}
    results = []
    for found, closed in [("2026-11-19 10:00", "2026-11-20 15:00"), ("11/19/2026 10:00", "11/20/2026 3:00 PM"),
                          (datetime(2026, 11, 19, 10, 0), datetime(2026, 11, 20, 15, 0))]:
        monkeypatch.setattr(records, "RECORDS_FILE", deficiencies_book(tmp_path, found, closed))
        rows = records.deficiencies("T01")
        assert (rows[1]["found_at"], rows[1]["closed_at"]) == ("2026-11-19 10:00", "2026-11-20 15:00")
        open_fixes = [(f["deficiency_id"], f["deadlines"], f["flags"]) for f in corrective.open_items(site, rows, NOW)]
        results.append((open_fixes, corrective.deficiency_deadlines(rows[1], site, rows, NOW)))
    assert results[0] == results[1] == results[2]
    assert results[0][0] and results[0][0][0][1]
    assert corrective.parse_local("11/20/2026 3:00 PM") == corrective.parse_local("2026-11-20 15:00")


def test_bad_found_at_names_file_row_field(tmp_path, monkeypatch):
    monkeypatch.setattr(records, "RECORDS_FILE", deficiencies_book(tmp_path, "19 Nov", None))
    with pytest.raises(ValueError, match=r"INSPECTOR_RECORDS.xlsx sheet deficiencies row 2 found_at: "
                                         r"unreadable time '19 Nov'"):
        records.deficiencies("T01")


# ---------- Add / Edit Site validation ----------
def admin_site(**kw):
    s = site_admin.new_site_defaults()
    s.update(site_id="T04", name="X", lat="47", lon="-122")
    s.update(kw)
    return s


CONTROLS = [{"control_id": "SF-1", "name": "Silt Fence", "inspect": "tears"}]


def test_site_admin_accepts_both_formats_and_compares_times(tmp_path):
    sites = raw_book(tmp_path / "INSPECTOR_RECORDS.xlsx")
    ok = admin_site(work_start="9:00", work_end="17:00", last_inspection="11/9/2026 9:00 AM")
    assert site_admin.validate(ok, CONTROLS, sites) == []         # '9:00' > '17:00' as text
    assert site_admin.validate(admin_site(work_start="7:00 AM", work_end="5:00 PM"), CONTROLS, sites) == []
    late = site_admin.validate(admin_site(work_start="5:00 PM", work_end="9:00"), CONTROLS, sites)
    assert any("must be earlier than work end" in e for e in late)
    bad = site_admin.validate(admin_site(work_end="5pm"), CONTROLS, sites)
    assert any("Work end '5pm'" in e for e in bad)
    row = site_admin.site_row(ok, CONTROLS, site_admin.SITE_COLUMNS)
    assert (row["work_start"], row["work_end"], row["last_inspection"]) == ("09:00", "17:00", "2026-11-09 09:00")


# ---------- Storm Triage shows a named error instead of crashing ----------
def test_triage_names_site_and_field_for_bad_work_start(monkeypatch):
    app = app_helpers()
    monkeypatch.setattr(app["records"], "inspections", lambda site_id=None: [])
    monkeypatch.setattr(app["records"], "deficiencies", lambda site_id=None: [])
    site = new_site().assign(work_start="7h", last_inspection="11/9/2026 9:00")
    table, problems = app["build_triage"](site, stations(), NOW)
    assert len(problems) == 1
    assert problems[0].startswith("T99: INSPECTOR_RECORDS.xlsx sheet sites work_start: unreadable time '7h'")
    assert "UNREADABLE_TIME" in table.iloc[0]["Flags"]


def test_triage_works_with_excel_formats(monkeypatch):
    app = app_helpers()
    monkeypatch.setattr(app["records"], "inspections", lambda site_id=None: [])
    monkeypatch.setattr(app["records"], "deficiencies", lambda site_id=None: [])
    excel = new_site().assign(work_start="7:00", work_end="5:00 PM", last_inspection="11/9/2026 9:00")
    iso = new_site().assign(work_start="07:00", work_end="17:00", last_inspection="2026-11-09 09:00")
    t_excel, p_excel = app["build_triage"](excel, stations(), NOW)
    t_iso, p_iso = app["build_triage"](iso, stations(), NOW)
    assert p_excel == p_iso == []
    assert t_excel.to_dict("records") == t_iso.to_dict("records")
