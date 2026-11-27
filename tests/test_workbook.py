"""data/INSPECTOR_RECORDS.xlsx: migration, reading, writing the sites sheet, and the Storm Triage regression.

Every test uses a temp workbook built from SAMPLE copies of the old CSVs; data/ is never touched.
"""
import csv
import shutil
from datetime import datetime, time, timezone

import pandas as pd
import pytest
from openpyxl import load_workbook

from agent import records, site_admin, swppp, workbook
from agent.timeparse import parse_local_datetime
from book_helpers import SAMPLE_CSVS, make_book, migration, raw_book, read_csv, sample_book, write_sample_csvs
from config import DATA, ROOT, SITE_STATIONS_FILE
from test_no_inspection import app_helpers

NOW = datetime(2026, 11, 27, 10, 15, 0)
AS_OF = datetime(2026, 11, 27, 19, 0, tzinfo=timezone.utc)


# ---------- Migration ----------
def test_round_trip_csv_to_workbook_gives_identical_records(tmp_path):
    src = write_sample_csvs(tmp_path / "data")
    originals = {name: read_csv(src / f"{name}.csv") for name in SAMPLE_CSVS}
    book, moved = migration.migrate(src)
    for name, (columns, rows) in originals.items():
        got_columns, got = workbook.read_sheet_rows(name, book)
        got = [r for _, r in got]
        assert got_columns == columns
        assert len(got) == len(rows)
        for want, have in zip(rows, got):
            for col in columns:
                if col in workbook.DATETIME_COLUMNS and want[col]:
                    assert parse_local_datetime(have[col]) == parse_local_datetime(want[col])
                elif col in workbook.CLOCK_COLUMNS:
                    assert have[col] == want[col]          # 07:00 stays 07:00
                else:
                    assert have[col] == want[col], (name, col)
    # lat/lon keep their exact text; times come back in the standard form
    _, sites = read_csv(src / "legacy_csv" / "sites.csv")
    assert workbook.read_sheet("sites", book)[0]["lat"] == sites[0]["lat"] == "47.2690"
    assert workbook.read_sheet("inspections", book)[0]["inspected_at"] == "2026-11-09 09:00"
    # the CSVs moved out of the way: one source of truth
    assert sorted(p.name for p in moved) == ["deficiencies.csv", "inspections.csv", "sites.csv"]
    assert not any((src / f"{n}.csv").exists() for n in SAMPLE_CSVS)
    assert all((src / "legacy_csv" / f"{n}.csv").exists() for n in SAMPLE_CSVS)


def test_migration_formats(tmp_path):
    book = sample_book(tmp_path)
    wb = load_workbook(book)
    assert wb.sheetnames == ["sites", "inspections", "deficiencies"]
    sites, insp, defs = wb["sites"], wb["inspections"], wb["deficiencies"]
    assert sites.freeze_panes == "A2" and sites["A1"].font.bold
    assert [c.value for c in insp[1]] == workbook.SHEETS["inspections"]
    assert insp["C2"].value == datetime(2026, 11, 9, 9, 0) and insp["C2"].number_format == "yyyy-mm-dd hh:mm"
    assert defs["I2"].value == datetime(2026, 11, 10, 14, 0)                       # closed_at
    assert sites["K2"].value == time(7, 0) and sites["K2"].number_format == "hh:mm"   # work_start
    assert sites["I2"].value == datetime(2026, 11, 16, 9, 0)                       # last_inspection
    assert sites["C2"].value == "47.2690" and sites["C2"].number_format == "@"     # lat as text
    assert sites.column_dimensions["B"].width > 20


def test_migration_refuses_to_overwrite(tmp_path):
    src = write_sample_csvs(tmp_path / "data")
    migration.migrate(src, move=False)
    before = (src / "INSPECTOR_RECORDS.xlsx").read_bytes()
    with pytest.raises(SystemExit, match="already exists"):
        migration.migrate(src)
    assert (src / "INSPECTOR_RECORDS.xlsx").read_bytes() == before
    assert (src / "sites.csv").exists()                                  # nothing moved
    migration.migrate(src, force=True)                                   # --force replaces it
    assert not (src / "sites.csv").exists()


# ---------- Reading ----------
def test_excel_datetime_cells_and_us_text_both_parse(tmp_path):
    cols = workbook.SHEETS["sites"]
    book = raw_book(tmp_path / "INSPECTOR_RECORDS.xlsx",
                    sites=(cols, [
                        ["T01", "A", 47.269, -122.4125, "B", "yes", "SF-1", "yes", datetime(2026, 11, 16, 9, 0),
                         "Mon-Fri", time(7, 0), time(17, 0), "no", "no"],
                        ["T02", "B", "47.2140", "-122.4740", "B", "no", "SF-2", "yes", "11/16/2026 9:00 AM",
                         "Mon-Fri", "7:00", "5:00 PM", "no", "no"],
                        ["T03", "C", 47.0, -122.5, "A", "no", "SF-3", "yes", 46342.375,     # serial number
                         "Mon-Sat", 0.2916666666666667, "15:00", "no", "yes"],
                    ]),
                    inspections=(workbook.SHEETS["inspections"], [
                        ["I-1", "T01", datetime(2026, 11, 9, 9, 0), "routine", "A"],
                        ["I-2", "T01", "11/9/2026 9:00", "routine", "A"],
                        ["I-3", "T01", "2026-11-09 09:00", "routine", "A"],
                        [None, None, None, None, None],                                    # blank row skipped
                        ["I-4", "T01", "Nov 9", "routine", "A"]]))
    t01, t02, t03 = workbook.read_sheet("sites", book)
    for site in (t01, t02):
        assert (site["last_inspection"], site["work_start"]) == ("2026-11-16 09:00", "07:00")
        assert site["work_end"] == "17:00"
    assert (t01["lat"], t01["lon"], t02["lat"]) == ("47.269", "-122.4125", "47.2140")   # no float artifacts
    assert (t03["lat"], t03["last_inspection"], t03["work_start"]) == ("47", "2026-11-16 09:00", "07:00")
    _, rows = workbook.read_sheet_rows("inspections", book)
    assert [r["inspected_at"] for _, r in rows] == ["2026-11-09 09:00"] * 3 + ["Nov 9"]   # bad text kept
    assert [n for n, _ in rows] == [2, 3, 4, 6]                                          # Excel row numbers


def test_missing_workbook_sheet_and_column_errors(tmp_path):
    missing = tmp_path / "INSPECTOR_RECORDS.xlsx"
    with pytest.raises(workbook.WorkbookError, match="INSPECTOR_RECORDS.xlsx was not found"):
        workbook.read_sheet("sites", missing)

    book = make_book(tmp_path / "INSPECTOR_RECORDS.xlsx")
    wb = load_workbook(book)
    wb["inspections"].title = "Inspections log"
    wb.save(book)
    workbook.clear_cache()
    with pytest.raises(workbook.WorkbookError, match="no sheet named 'inspections'.*Inspections log"):
        workbook.check(book)

    cols = [c for c in workbook.SHEETS["deficiencies"] if c != "found_at"]
    book = raw_book(tmp_path / "INSPECTOR_RECORDS.xlsx", deficiencies=(cols, []))
    with pytest.raises(workbook.WorkbookError, match="sheet 'deficiencies' is missing column\\(s\\): found_at"):
        workbook.read_sheet("deficiencies", book)


def test_unreadable_or_locked_file_says_close_excel(tmp_path, monkeypatch):
    bad = tmp_path / "INSPECTOR_RECORDS.xlsx"
    bad.write_bytes(b"half-saved, not a zip")
    with pytest.raises(workbook.WorkbookError, match="Close INSPECTOR_RECORDS.xlsx in Excel and press F5."):
        workbook.read_sheet("sites", bad)

    book = sample_book(tmp_path / "ok")

    def locked(self):
        raise PermissionError(13, "The process cannot access the file")
    monkeypatch.setattr(type(book), "read_bytes", locked)
    workbook.clear_cache()
    with pytest.raises(workbook.WorkbookError, match="^Close INSPECTOR_RECORDS.xlsx in Excel and press F5.$"):
        workbook.read_sheet("sites", book)


def test_records_read_the_workbook(tmp_path, monkeypatch):
    monkeypatch.setattr(records, "RECORDS_FILE", sample_book(tmp_path))
    assert [r["inspection_id"] for r in records.inspections("T01")] == ["I-001", "I-002", "I-001"]
    assert records.last_inspection("T01") == "2026-11-25 09:00"
    assert [d["deficiency_id"] for d in records.deficiencies("T02")] == ["D-004"]


def test_app_load_sites_same_shape_as_csv(tmp_path):
    app = app_helpers()
    src = write_sample_csvs(tmp_path / "data")
    old = pd.read_csv(src / "sites.csv", dtype=str).fillna("")         # what load_sites used to do
    old["lat"], old["lon"] = old["lat"].astype(float), old["lon"].astype(float)
    book, _ = migration.migrate(src)
    new = app["load_sites"](book)
    assert list(new.columns) == list(old.columns)
    assert new["lat"].dtype == float and new["site_id"].tolist() == old["site_id"].tolist()
    for col in ["name", "control_ids", "frequency_option", "impaired_water", "work_days", "work_start"]:
        assert new[col].tolist() == old[col].tolist()
    assert (new["lat"] == old["lat"]).all() and (new["lon"] == old["lon"]).all()


def test_page_shows_workbook_error_instead_of_crashing(monkeypatch):
    from streamlit.testing.v1 import AppTest

    def broken(path=None):
        raise workbook.WorkbookError(workbook.CLOSE_EXCEL)
    monkeypatch.setattr(workbook, "check", broken)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception
    assert sum(e.value == "Close INSPECTOR_RECORDS.xlsx in Excel and press F5." for e in at.error) >= 4  # all tabs


# ---------- Writing the sites sheet (Add / Edit Site) ----------
@pytest.fixture
def admin_files(tmp_path, monkeypatch):
    swppps = tmp_path / "swppps"
    shutil.copytree(DATA / "swppps", swppps)
    monkeypatch.setattr(swppp, "SWPPP_DIR", swppps)
    return {"records_file": sample_book(tmp_path), "swppp_dir": swppps, "backup_dir": tmp_path / "backups"}


def new_site():
    s = site_admin.new_site_defaults()
    s.update(site_id="T04", name="SAMPLE New Yard", lat="47.2500", lon="-122.4500", last_inspection="11/20/2026 8:00")
    return s


CONTROLS = [{"control_id": "SF-9", "name": "Silt Fence", "inspect": "tears, sediment depth"}]


def sheet_cells(book, name):
    ws = load_workbook(book)[name]
    return [[(c.value, c.number_format) for c in row] for row in ws.iter_rows()]


def test_site_save_keeps_other_sheets_and_backs_up(admin_files):
    book = admin_files["records_file"]
    original = book.read_bytes()
    before = {n: sheet_cells(book, n) for n in ("inspections", "deficiencies")}
    text = site_admin.build_swppp(new_site(), CONTROLS)
    errors, backups = site_admin.save_site(new_site(), CONTROLS, text, now=NOW, **admin_files)
    assert errors == []
    assert {n: sheet_cells(book, n) for n in before} == before          # values and formats unchanged
    assert load_workbook(book).sheetnames == ["sites", "inspections", "deficiencies"]
    backup = admin_files["backup_dir"] / "INSPECTOR_RECORDS_20261127_101500.xlsx"
    assert backup in backups and backup.read_bytes() == original
    columns, rows = site_admin.read_sites(book)
    assert columns == site_admin.SITE_COLUMNS
    assert [r["site_id"] for r in rows] == ["T01", "T02", "T03", "T04"]
    assert rows[-1]["last_inspection"] == "2026-11-20 08:00" and rows[-1]["control_ids"] == "SF-9"
    ws = load_workbook(book)["sites"]
    assert ws["I5"].value == datetime(2026, 11, 20, 8, 0) and ws["I5"].number_format == "yyyy-mm-dd hh:mm"
    assert ws["K5"].value == time(7, 0) and ws["C5"].value == "47.2500"
    assert ws.freeze_panes == "A2" and ws["A1"].font.bold


def test_locked_workbook_gives_friendly_error_and_writes_nothing(admin_files, monkeypatch):
    book = admin_files["records_file"]
    original = book.read_bytes()
    text = site_admin.build_swppp(new_site(), CONTROLS)

    monkeypatch.setattr(site_admin, "is_locked", lambda path: True)       # Excel has it open
    errors, backups = site_admin.save_site(new_site(), CONTROLS, text, now=NOW, **admin_files)
    assert errors == ["INSPECTOR_RECORDS.xlsx is open in Excel. Close it and click Save again."]
    assert backups == [] and not admin_files["backup_dir"].exists()

    monkeypatch.setattr(site_admin, "is_locked", lambda path: False)      # Excel grabs it during the save

    def replace(src, dst):
        raise PermissionError(13, "The process cannot access the file")
    monkeypatch.setattr(site_admin.os, "replace", replace)
    errors, backups = site_admin.save_site(new_site(), CONTROLS, text, now=NOW, **admin_files)
    assert errors == [site_admin.LOCKED_MESSAGE] and backups == []
    assert book.read_bytes() == original
    assert not (admin_files["swppp_dir"] / "T04.md").exists()
    assert not list(admin_files["backup_dir"].glob("*"))                   # half-made backups removed
    assert not list(book.parent.glob("*.saving.xlsx"))


def test_is_locked_false_for_closed_file(tmp_path):
    assert site_admin.is_locked(sample_book(tmp_path)) is False


# ---------- Regression: Storm Triage identical before and after the move ----------
def csv_rows(path, site_id):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]
    return [r for r in rows if site_id is None or r["site_id"] == site_id]


@pytest.mark.skipif(not SITE_STATIONS_FILE.exists(), reason="needs the saved rain cache")
def test_storm_triage_same_with_workbook_as_with_csvs(tmp_path, monkeypatch):
    app = app_helpers()
    stations = app["load_site_stations"]()
    src = write_sample_csvs(tmp_path / "data")

    # Before: the CSV version (old load_sites + CSV log rows exactly as written)
    old_sites = pd.read_csv(src / "sites.csv", dtype=str).fillna("")
    old_sites["lat"], old_sites["lon"] = old_sites["lat"].astype(float), old_sites["lon"].astype(float)
    with monkeypatch.context() as m:
        m.setattr(records, "inspections", lambda site_id=None: csv_rows(src / "inspections.csv", site_id))
        m.setattr(records, "deficiencies", lambda site_id=None: csv_rows(src / "deficiencies.csv", site_id))
        before, before_problems = app["build_triage"](old_sites, stations, AS_OF)
        before_ctx = [app["site_context"](s, stations, AS_OF) for _, s in old_sites.iterrows()]

    # After: the migrated workbook
    book, _ = migration.migrate(src)
    monkeypatch.setattr(records, "RECORDS_FILE", book)
    new_sites = app["load_sites"](book)
    after, after_problems = app["build_triage"](new_sites, stations, AS_OF)
    after_ctx = [app["site_context"](s, stations, AS_OF) for _, s in new_sites.iterrows()]

    assert before_problems == after_problems == []
    assert sorted(before["Site"]) == ["T01", "T02", "T03"]
    cols = ["Site", "Priority", "Next due", "Due for", "Rule", "Flags", "Also due", "Open fixes",
            "0.25 in reached (since last insp.)"]
    assert before[cols].to_dict("records") == after[cols].to_dict("records")
    for b, a in zip(before_ctx, after_ctx):
        assert b["items"] == a["items"]                                    # every due date and flag
        assert [(f["deadlines"], f["flags"]) for f in b["fixes"]] == [(f["deadlines"], f["flags"]) for f in a["fixes"]]
        assert parse_local_datetime(b["site"]["last_inspection"]) == parse_local_datetime(a["site"]["last_inspection"])
