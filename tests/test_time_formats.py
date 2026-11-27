"""Log times saved by Excel in US format ("11/9/2026 9:00") must parse the same as ISO times."""
from datetime import datetime, timezone

import pytest

from agent import corrective, records, site_admin, workbook
from agent.scheduler import site_schedule
from book_helpers import make_book
from test_no_inspection import app_helpers, new_site, stations

NOW = datetime(2026, 12, 31, tzinfo=timezone.utc)


@pytest.mark.parametrize("text, expected", [
    ("2026-11-09 09:00", datetime(2026, 11, 9, 9, 0)),
    ("2026-11-09 09:00:30", datetime(2026, 11, 9, 9, 0, 30)),
    ("11/9/2026 9:00", datetime(2026, 11, 9, 9, 0)),
    ("11/09/2026 21:05", datetime(2026, 11, 9, 21, 5)),
    ("11/9/2026 9:00:00", datetime(2026, 11, 9, 9, 0)),
    ("11/9/2026 9:00 PM", datetime(2026, 11, 9, 21, 0)),
    ("11/9/2026 12:30 am", datetime(2026, 11, 9, 0, 30)),
    ("11/9/2026", datetime(2026, 11, 9, 0, 0)),
    ("  11/9/2026   9:00  ", datetime(2026, 11, 9, 9, 0)),
])
def test_parse_local_time_formats(text, expected):
    got = records.parse_local_time(text)
    assert got == expected and got.tzinfo is None


@pytest.mark.parametrize("bad", ["Nov 9 2026", "9/31/2026 9:00", "2026-11-09 25:00", "", "13/1/2026"])
def test_parse_local_time_rejects(bad):
    with pytest.raises(ValueError, match="unreadable time"):
        records.parse_local_time(bad)


def inspection_log(tmp_path, monkeypatch, times):
    """Temp workbook whose inspections sheet has one T01 row per time; records.py reads it."""
    rows = [{"inspection_id": f"I{i}", "site_id": "T01", "inspected_at": t, "type": "routine", "inspector": "A"}
            for i, t in enumerate(times, start=1)]
    book = make_book(tmp_path / "INSPECTOR_RECORDS.xlsx", inspections=(workbook.SHEETS["inspections"], rows))
    monkeypatch.setattr(records, "RECORDS_FILE", book)


def test_error_names_file_row_and_value(tmp_path, monkeypatch):
    inspection_log(tmp_path, monkeypatch, ["11/9/2026 9:00", "Nov 16 2026"])
    with pytest.raises(ValueError) as err:
        records.last_inspection("T01")
    assert "INSPECTOR_RECORDS.xlsx sheet inspections row 3 inspected_at" in str(err.value)
    assert "'Nov 16 2026'" in str(err.value)
    assert records.inspections("T02") == []          # another site's bad row doesn't block this one


def test_last_inspection_compares_datetimes_not_strings(tmp_path, monkeypatch):
    # 11/10 is later, though '11/10' < '11/9' as text
    inspection_log(tmp_path, monkeypatch, ["11/9/2026 17:00", "11/10/2026 8:00 AM", "2026-11-02 08:00"])
    assert records.last_inspection("T01") == "2026-11-10 08:00"


def test_bad_sites_fallback_named(monkeypatch):
    monkeypatch.setattr(records, "inspections", lambda site_id=None: [])
    with pytest.raises(ValueError, match=r"sheet sites, site T09, last_inspection: unreadable time 'yesterday'"):
        records.last_inspection("T09", "yesterday")


def test_us_and_iso_give_same_schedule_and_deadlines():
    base = {"site_id": "T1", "frequency_option": "A", "impaired_water": "no"}
    iso = site_schedule({**base, "last_inspection": "2026-11-09 08:00"}, [], NOW)
    us = site_schedule({**base, "last_inspection": "11/9/2026 8:00 AM"}, [], NOW)
    assert iso == us
    fix = {"control_id": "SF-1", "description": "", "category": "routine_maintenance", "status": "open"}
    a = corrective.deficiency_deadlines({**fix, "found_at": "2026-11-19 10:00"}, base, [], NOW)
    b = corrective.deficiency_deadlines({**fix, "found_at": "11/19/2026 10:00"}, base, [], NOW)
    assert a == b
    assert corrective.parse_local("") is None


def test_site_admin_accepts_us_last_inspection(tmp_path):
    sites = make_book(tmp_path / "INSPECTOR_RECORDS.xlsx")
    site = site_admin.new_site_defaults()
    site.update(site_id="T04", name="X", lat="47", lon="-122")
    controls = [{"control_id": "SF-1", "name": "Silt Fence", "inspect": "tears"}]
    assert site_admin.validate({**site, "last_inspection": "11/9/2026 9:00"}, controls, sites) == []
    errors = site_admin.validate({**site, "last_inspection": "soon"}, controls, sites)
    assert any("Last inspection 'soon'" in e for e in errors)


def test_triage_shows_error_instead_of_crashing(monkeypatch):
    app = app_helpers()
    bad = [{"inspection_id": "I1", "site_id": "T99", "inspected_at": "Nov 9", "type": "routine", "inspector": "A"}]

    def inspections(site_id=None):
        records.parse_local_time(bad[0]["inspected_at"], "INSPECTOR_RECORDS.xlsx sheet inspections", 2)

    monkeypatch.setattr(app["records"], "inspections", inspections)
    monkeypatch.setattr(app["records"], "deficiencies", lambda site_id=None: [])
    table, problems = app["build_triage"](new_site(), stations(), NOW)
    assert len(problems) == 1
    assert "T99" in problems[0] and "sheet inspections row 2" in problems[0] and "'Nov 9'" in problems[0]
    assert table.iloc[0]["Priority"] == "CHECK DATA" and "UNREADABLE_TIME" in table.iloc[0]["Flags"]
    with pytest.raises(ValueError):           # the Checklist/Report tabs catch this and show st.error
        app["site_context"](new_site().iloc[0], stations(), NOW)
