"""Site Records tab: editing the sites / inspections / deficiencies sheets (agent/site_admin.py). No AI.

Every test uses a temp workbook built from the SAMPLE data; data/ is never touched.
"""
import copy
import inspect
from datetime import datetime, time, timezone

import pandas as pd
import pytest
from openpyxl import load_workbook

from agent import corrective, records, site_admin, workbook
from book_helpers import sample_book
from config import ROOT

ROW = site_admin.ROW_KEY
NOW = datetime(2026, 11, 27, 12, 0)                          # site-local, naive (as the workbook stores times)
NOW_UTC = datetime(2026, 11, 27, 20, 0, tzinfo=timezone.utc)  # the same moment, for corrective/scheduler


@pytest.fixture
def book(tmp_path, monkeypatch):
    path = sample_book(tmp_path)
    monkeypatch.setattr(records, "RECORDS_FILE", path)
    return path


def loaded(book, sheet):
    """What the tab loads: row dicts of text carrying their Excel row number."""
    _, rows = workbook.read_sheet_rows(sheet, book)
    return [{ROW: n, **r} for n, r in rows]


def save(book, sheet, original, edited, who="Pat Lee"):
    return site_admin.save_sheet_edits(sheet, original, edited, who, records_file=book,
                                       backup_dir=book.parent / "backups", now=NOW)


def sheet_cells(book, name):
    ws = load_workbook(book)[name]
    return [[(c.value, c.number_format) for c in row] for row in ws.iter_rows()]


def new_inspection(**kw):
    row = {ROW: None, "inspection_id": "", "site_id": "T02", "inspected_at": "2026-11-26 10:00",
           "type": "storm", "inspector": "Pat Lee"}
    row.update(kw)
    return row


def new_deficiency(**kw):
    row = {ROW: None, "deficiency_id": "", "site_id": "T02", "inspection_id": "I-006", "control_id": "SF-2",
           "found_at": "2026-11-26 10:15", "description": "Silt fence sagging at east line",
           "category": "routine_maintenance", "status": "open", "closed_at": ""}
    row.update(kw)
    return row


# ---------- Sites ----------
def test_edit_a_site_row(book):
    original = loaded(book, "sites")
    edited = copy.deepcopy(original)
    edited[1].update(name="SAMPLE Renamed Apartments", work_end="16:30", has_manual_gauge="yes")
    others = {n: sheet_cells(book, n) for n in ("inspections", "deficiencies")}
    before = book.read_bytes()

    errors, backups, plan = save(book, "sites", original, edited)
    assert errors == []
    assert [c["id"] for c in plan["changed"]] == ["T02"] and plan["added"] == []
    after = {r["site_id"]: r for r in site_admin.read_sites(book)[1]}
    assert after["T02"]["name"] == "SAMPLE Renamed Apartments" and after["T02"]["work_end"] == "16:30"
    assert after["T02"]["updated_by"] == "Pat Lee" and after["T02"]["updated_at"] == "2026-11-27 12:00"
    assert after["T01"]["updated_by"] == "" and after["T01"]["name"] == original[0]["name"]     # untouched
    ws = load_workbook(book)["sites"]
    assert ws["L3"].value == time(16, 30) and ws["L3"].number_format == "hh:mm"
    assert [c.value for c in ws[1]][-2:] == ["updated_by", "updated_at"] and ws["P1"].font.bold
    assert {n: sheet_cells(book, n) for n in others} == others                                  # other sheets kept
    assert [b.name for b in backups] == ["INSPECTOR_RECORDS_20261127_120000.xlsx"]
    assert backups[0].read_bytes() == before                                                    # whole workbook


def test_sites_cannot_add_remove_or_rename(book):
    original = loaded(book, "sites")
    added = copy.deepcopy(original) + [{ROW: None, **site_admin.new_site_defaults(), "site_id": "T09", "name": "X"}]
    assert any("Add new sites on the Add Site tab" in e for e in save(book, "sites", original, added)[0])
    removed = copy.deepcopy(original)[:2]
    assert any("Sites can't be removed (T03)" in e for e in save(book, "sites", original, removed)[0])
    renamed = copy.deepcopy(original)
    renamed[0]["site_id"] = "T10"
    assert any("site_id can't be changed" in e for e in save(book, "sites", original, renamed)[0])


@pytest.mark.parametrize("change, message", [
    ({"lat": "95"}, "Latitude must be between -90 and 90"),
    ({"lon": "-200"}, "Longitude must be between -180 and 180"),
    ({"frequency_option": "C"}, "Frequency option must be A or B"),
    ({"active": "maybe"}, "Active must be yes or no"),
    ({"work_days": "Mon-Funday"}, "Work days 'Mon-Funday' is not understood"),
    ({"work_start": "17:00", "work_end": "07:00"}, "must be earlier than work end"),
    ({"control_ids": "SF-1;silt"}, "control ID 'silt' must be 2-3 capital letters"),
    ({"control_ids": ""}, "control_ids needs at least one control ID"),
    ({"name": ""}, "Site name is required"),
])
def test_site_row_rules(book, change, message):
    original = loaded(book, "sites")
    edited = copy.deepcopy(original)
    edited[0].update(change)
    before = book.read_bytes()
    errors, backups, _ = save(book, "sites", original, edited)
    assert any(e.startswith("Site T01: ") and message in e for e in errors), errors
    assert backups == [] and book.read_bytes() == before


# ---------- Inspections ----------
def test_add_inspection_gets_next_id_and_changes_last_inspection(book):
    assert records.last_inspection("T02") == "2026-11-25 11:00"
    original = loaded(book, "inspections")
    errors, _, plan = save(book, "inspections", original, copy.deepcopy(original) + [new_inspection()])
    assert errors == []
    assert [r["inspection_id"] for r in plan["added"]] == ["I-006"]
    assert records.last_inspection("T02") == "2026-11-26 10:00"                 # due dates now count from here
    added = records.inspections("T02")[-1]
    assert (added["inspection_id"], added["updated_by"], added["updated_at"]) == ("I-006", "Pat Lee", "2026-11-27 12:00")
    ws = load_workbook(book)["inspections"]
    assert ws.cell(ws.max_row, 3).value == datetime(2026, 11, 26, 10, 0)       # a real Excel date-time


def test_two_new_rows_get_consecutive_ids_and_typed_duplicates_refused(book):
    original = loaded(book, "inspections")
    plan, errors = site_admin.plan_sheet_edits("inspections", original,
                                               original + [new_inspection(), new_inspection(site_id="T01")],
                                               site_admin.read_sites(book)[1], NOW)
    assert errors == [] and [r["inspection_id"] for r in plan["added"]] == ["I-006", "I-007"]
    _, errors = site_admin.plan_sheet_edits("inspections", original, original + [new_inspection(inspection_id="I-002")],
                                            site_admin.read_sites(book)[1], NOW)
    assert any("I-002 is already used" in e for e in errors)


def test_deleting_an_existing_row_is_blocked(book):
    original = loaded(book, "inspections")
    edited = [r for r in copy.deepcopy(original) if r["inspection_id"] != "I-003"] + [new_inspection()]
    before = book.read_bytes()
    errors, backups, _ = save(book, "inspections", original, edited)
    assert any("Deleting rows is not allowed (I-003, I-003)" in e or "Deleting rows is not allowed (I-003)" in e
               for e in errors), errors
    assert backups == [] and book.read_bytes() == before


def test_existing_id_is_read_only(book):
    original = loaded(book, "deficiencies")
    edited = copy.deepcopy(original)
    edited[0]["deficiency_id"] = "D-100"
    assert any("deficiency_id can't be changed" in e for e in save(book, "deficiencies", original, edited)[0])


@pytest.mark.parametrize("change, message", [
    ({"site_id": "T99"}, "Site ID 'T99' is not in the sites sheet"),
    ({"inspected_at": ""}, "Inspected at is required"),
    ({"inspected_at": "2026-11-28 08:00"}, "Inspected at 2026-11-28 08:00 is in the future"),
    ({"inspected_at": "tomorrow"}, "Inspected at 'tomorrow' is not a date and time"),
    ({"type": "weekly"}, "Type must be routine or storm"),
    ({"inspector": ""}, "Inspector is required"),
])
def test_inspection_rules(book, change, message):
    original = loaded(book, "inspections")
    errors, _, _ = save(book, "inspections", original, original + [new_inspection(**change)])
    assert any(e.startswith("Inspection I-006: ") and message in e for e in errors), errors


# ---------- Deficiencies ----------
def test_close_a_deficiency_drops_it_from_open_items(book):
    site = {r["site_id"]: r for r in site_admin.read_sites(book)[1]}["T02"]
    original = loaded(book, "deficiencies")
    assert save(book, "deficiencies", original, original + [new_deficiency()])[0] == []
    assert [d["deficiency_id"] for d in corrective.open_items(site, records.deficiencies("T02"), NOW_UTC)] == ["D-006"]

    original = loaded(book, "deficiencies")
    edited = copy.deepcopy(original)
    d006 = next(r for r in edited if r["deficiency_id"] == "D-006")
    d006.update(status="closed", closed_at="2026-11-27 09:00")
    errors, _, plan = save(book, "deficiencies", original, edited)
    assert errors == []
    assert site_admin.describe_plan(plan) == [
        "Change D-006 (Excel row 7): status: 'open' -> 'closed'; closed_at: '' -> '2026-11-27 09:00'"]
    assert corrective.open_items(site, records.deficiencies("T02"), NOW_UTC) == []


@pytest.mark.parametrize("change, message", [
    ({"site_id": "T99"}, "Site ID 'T99' is not in the sites sheet"),
    ({"control_id": "SF-1"}, "Control 'SF-1' is not one of site T02's controls (SF-2, IP-1)"),
    ({"found_at": ""}, "Found at is required"),
    ({"found_at": "2026-12-01 08:00"}, "Found at 2026-12-01 08:00 is in the future"),
    ({"category": "cosmetic"}, "Category must be routine_maintenance"),
    ({"status": "pending"}, "Status must be open or closed"),
    ({"status": "closed"}, "A closed deficiency needs closed_at"),
    ({"status": "closed", "closed_at": "2026-11-26 09:00"}, "can't be before found at (2026-11-26 10:15)"),
    ({"status": "closed", "closed_at": "2026-11-28 09:00"}, "Closed at 2026-11-28 09:00 is in the future"),
    ({"status": "open", "closed_at": "2026-11-27 09:00"}, "An open deficiency must have a blank closed_at"),
    ({"description": ""}, "Description is required"),
])
def test_deficiency_rules(book, change, message):
    original = loaded(book, "deficiencies")
    errors, backups, _ = save(book, "deficiencies", original, original + [new_deficiency(**change)])
    assert any(e.startswith("Deficiency D-006: ") and message in e for e in errors), errors
    assert backups == []


# ---------- Saving: only that sheet, backups, nothing-to-save, locked file ----------
def test_save_writes_only_that_sheet(book):
    sites, defs = sheet_cells(book, "sites"), sheet_cells(book, "deficiencies")
    original = loaded(book, "inspections")
    assert save(book, "inspections", original, original + [new_inspection()])[0] == []
    assert sheet_cells(book, "sites") == sites and sheet_cells(book, "deficiencies") == defs
    assert load_workbook(book).sheetnames == ["sites", "inspections", "deficiencies"]


def test_no_changes_and_saved_by_required(book):
    original = loaded(book, "inspections")
    assert save(book, "inspections", original, copy.deepcopy(original))[0] == [site_admin.NO_CHANGES]
    errors, backups, _ = save(book, "inspections", original, original + [new_inspection()], who="  ")
    assert errors == ["Enter your name in Saved by."] and backups == []


def test_locked_workbook_friendly_error(book, monkeypatch):
    original = loaded(book, "inspections")
    edited = original + [new_inspection()]
    before = book.read_bytes()
    monkeypatch.setattr(site_admin, "is_locked", lambda path: True)
    errors, backups, _ = save(book, "inspections", original, edited)
    assert errors == ["INSPECTOR_RECORDS.xlsx is open in Excel. Close it and click Save again."] and backups == []

    monkeypatch.setattr(site_admin, "is_locked", lambda path: False)

    def replace(src, dst):
        raise PermissionError(13, "The process cannot access the file")
    monkeypatch.setattr(site_admin.os, "replace", replace)
    errors, backups, _ = save(book, "inspections", original, edited)
    assert errors == [site_admin.LOCKED_MESSAGE] and backups == []
    assert book.read_bytes() == before and not list((book.parent / "backups").glob("*"))


def test_workbook_changed_since_loading_is_refused(book):
    original = loaded(book, "deficiencies")
    edited = copy.deepcopy(original)
    edited[0]["description"] = "Edited on the page"
    wb = load_workbook(book)                                 # someone re-sorts the sheet in Excel meanwhile
    ws = wb["deficiencies"]
    ws["A2"], ws["A3"] = ws["A3"].value, ws["A2"].value
    wb.save(book)
    workbook.clear_cache()
    errors, backups, _ = save(book, "deficiencies", original, edited)
    assert "changed since this page loaded" in errors[0] and backups == []


def test_editor_text_converts_editor_values():
    assert site_admin.editor_text("inspected_at", pd.Timestamp("2026-11-26 10:00")) == "2026-11-26 10:00"
    assert site_admin.editor_text("closed_at", pd.NaT) == ""
    assert site_admin.editor_text("work_start", time(7, 0)) == "07:00"
    assert site_admin.editor_text("lat", 47.269) == "47.269"
    assert site_admin.editor_text("lat", float("nan")) == ""
    assert site_admin.editor_text("inspector", None) == ""
    assert site_admin.next_id("D-", ["D-001", "D-012", "X-9"]) == "D-013"


# ---------- Add Site is new-site only; the tabs ----------
def test_add_site_has_no_edit_mode(tmp_path):
    for fn in (site_admin.save_site, site_admin.validate):
        assert "is_new" not in inspect.signature(fn).parameters
    assert not hasattr(site_admin, "text_sections_from")
    site = {**site_admin.new_site_defaults(), "site_id": "T01", "name": "X", "lat": "47", "lon": "-122"}
    errors = site_admin.validate(site, [{"control_id": "SF-1", "name": "Silt", "inspect": "tears"}],
                                 sample_book(tmp_path))
    assert any("already exists. Edit it on the Site Records tab" in e for e in errors)


def test_tabs_and_record_editors_render(book, monkeypatch):
    """Whole page on the temp workbook: renamed tabs, no site selector on Add Site, three collapsed record
    editors, and ticking Show changes with no edits finds nothing to save (the editor round trip is exact)."""
    from streamlit.testing.v1 import AppTest
    import config
    monkeypatch.setattr(config, "INSPECTOR_RECORDS", book)
    monkeypatch.setattr(workbook.read_sheet_rows, "__defaults__", (book,))
    monkeypatch.setattr(workbook.check, "__defaults__", (book,))
    monkeypatch.setattr(site_admin.read_sites, "__defaults__", (book,))
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Storm Triage", "Site Records", "Draft Report", "Verification", "Add Site"]
    assert "sa_pick" not in [s.key for s in at.selectbox]
    assert [e.label for e in at.expander if e.label in ("Sites", "Inspections", "Deficiencies")] == \
        ["Sites", "Inspections", "Deficiencies"]
    assert {"Save sites", "Save inspections", "Save deficiencies", "Save site"} <= {b.label for b in at.button}
    for cb in at.checkbox:
        if cb.label == "Show changes":
            cb.check()
    at.run()
    assert not at.exception
    assert [i.value for i in at.info].count(site_admin.NO_CHANGES) == 3
    assert not at.warning
