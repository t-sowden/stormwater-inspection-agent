"""Read the inspection log and deficiency list. This module only reads them; inspector saves on the
Site Records tab go through agent/site_admin.py.

Both live in data/INSPECTOR_RECORDS.xlsx (Alex replaces the DRAFT rows; keep the sheet and column names):
  sheet "inspections"   inspection_id, site_id, inspected_at, type, inspector
  sheet "deficiencies"  deficiency_id, site_id, inspection_id, control_id, found_at,
                        description, category, status, closed_at
Times are site-local. Cells may be real Excel date-times or text written YYYY-MM-DD HH:MM or
M/D/YYYY H:MM (Excel's US style); agent/workbook.py returns them as "YYYY-MM-DD HH:MM".
"""
from agent import workbook
from agent.timeparse import parse_local_datetime
from config import INSPECTOR_RECORDS

RECORDS_FILE = INSPECTOR_RECORDS


def parse_local_time(text, file=None, row=None, field=None):
    """timeparse.parse_local_datetime, with the file, row, and field named in any error."""
    where = " ".join(p for p in (str(file) if file else "", f"row {row}" if row is not None else "",
                                 field or "") if p)
    return parse_local_datetime(text, where or None)


def _site_rows(sheet, site_id, time_columns):
    """Rows for one site (or all), after checking their time cells parse. Errors name sheet, row, field."""
    _, rows = workbook.read_sheet_rows(sheet, RECORDS_FILE)
    rows = [(n, r) for n, r in rows if site_id is None or r["site_id"] == site_id]
    for n, r in rows:
        for col in time_columns:
            if r.get(col):
                parse_local_time(r[col], f"{RECORDS_FILE.name} sheet {sheet}", n, col)
    return [r for _, r in rows]


def inspections(site_id=None):
    return _site_rows("inspections", site_id, ["inspected_at"])


def deficiencies(site_id=None):
    return _site_rows("deficiencies", site_id, ["found_at", "closed_at"])


def last_inspection(site_id, fallback=""):
    """Latest inspected_at for the site from the log; falls back to the sites sheet's last_inspection.

    Returns the time text as read; a bad fallback raises a ValueError naming the sites sheet.
    """
    times = [r["inspected_at"] for r in inspections(site_id) if r.get("inspected_at")]
    if times:
        return max(times, key=parse_local_time)
    if str(fallback).strip():
        parse_local_time(fallback, f"{RECORDS_FILE.name} sheet sites, site {site_id},", None, "last_inspection")
    return fallback
