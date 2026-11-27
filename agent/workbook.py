"""Read data/INSPECTOR_RECORDS.xlsx (sheets "sites", "inspections", "deficiencies"). READ-ONLY.

Every value comes back as a string, the same as the old CSVs:
  datetimes "YYYY-MM-DD HH:MM", clock times "HH:MM", blanks "", numbers as plain text (47.269, not 47.269000000001).
Cells may be real Excel dates/times or text in either "2026-11-09 09:00" or Excel's US "11/9/2026 9:00" style.
The file is read into memory first, so it can be read while Excel has it open.
Writing the "sites" sheet is done by agent/site_admin.py; the migration script creates the workbook.
"""
from datetime import date, datetime, time
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel
from openpyxl.utils.exceptions import InvalidFileException

from agent.timeparse import clock_text, datetime_text, parse_clock, parse_local_datetime
from config import INSPECTOR_RECORDS

SHEETS = {
    "sites": ["site_id", "name", "lat", "lon", "frequency_option", "impaired_water", "control_ids", "active",
              "last_inspection", "work_days", "work_start", "work_end", "works_holidays", "has_manual_gauge"],
    "inspections": ["inspection_id", "site_id", "inspected_at", "type", "inspector"],
    "deficiencies": ["deficiency_id", "site_id", "inspection_id", "control_id", "found_at", "description",
                     "category", "status", "closed_at"],
}
# Columns the app cannot work without (sites: work_* and the rest fall back to config defaults).
REQUIRED = {
    "sites": SHEETS["sites"][:9],
    "inspections": SHEETS["inspections"],
    "deficiencies": SHEETS["deficiencies"],
}
DATETIME_COLUMNS = {"last_inspection", "inspected_at", "found_at", "closed_at", "updated_at"}
CLOCK_COLUMNS = {"work_start", "work_end"}
DATETIME_FORMAT = "yyyy-mm-dd hh:mm"
CLOCK_FORMAT = "hh:mm"
TEXT_FORMAT = "@"
CLOSE_EXCEL = "Close INSPECTOR_RECORDS.xlsx in Excel and press F5."

_CACHE = {}


class WorkbookError(ValueError):
    """The workbook, a sheet, or a column is missing or unreadable. The message is shown to the user."""


# ---------- Cell conversion ----------
def _number_text(value):
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value)


def cell_text(column, value):
    """One cell -> the string the app uses."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if column in CLOCK_COLUMNS:
        if isinstance(value, (datetime, time)):
            return clock_text(value)
        if isinstance(value, (int, float)) and 0 <= value < 1:          # time stored as a day fraction
            minutes = round(value * 24 * 60)
            return clock_text(time(minutes // 60 % 24, minutes % 60))
    if column in DATETIME_COLUMNS:
        if isinstance(value, datetime):
            return datetime_text(value)
        if isinstance(value, date):
            return datetime_text(datetime.combine(value, time()))
        if isinstance(value, (int, float)) and value >= 1:              # date stored as a serial number
            return datetime_text(from_excel(value))
    if isinstance(value, datetime):
        return datetime_text(value)
    if isinstance(value, time):
        return clock_text(value)
    if isinstance(value, (int, float)):
        return _number_text(value)
    text = " ".join(str(value).split())
    try:                                    # text in either format -> the standard one
        if column in DATETIME_COLUMNS and text:
            return datetime_text(parse_local_datetime(text))
        if column in CLOCK_COLUMNS and text:
            return clock_text(parse_clock(text))
    except ValueError:
        pass                                # left as typed; records.py names the file, row, and field
    return text


def cell_value(column, text):
    """App string -> (cell value, number format) for writing: real dates/times for time columns, else text."""
    text = "" if text is None else str(text).strip()
    if not text:
        return None, None
    try:
        if column in DATETIME_COLUMNS:
            return parse_local_datetime(text), DATETIME_FORMAT
        if column in CLOCK_COLUMNS:
            return parse_clock(text), CLOCK_FORMAT
    except ValueError:
        pass
    return text, TEXT_FORMAT


# ---------- Reading ----------
def _load(path):
    """{sheet title: [row tuples]} for the whole workbook, cached until the file changes."""
    path = Path(path)
    try:
        stat = path.stat()
    except FileNotFoundError:
        raise WorkbookError(f"{path.name} was not found in {path.parent}. Create it with: "
                            "uv run python scripts/make_inspector_records.py") from None
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    if key in _CACHE:
        return _CACHE[key]
    try:
        data = path.read_bytes()            # a copy in memory: works while Excel has the file open
    except OSError:
        raise WorkbookError(CLOSE_EXCEL) from None
    try:
        wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except (BadZipFile, InvalidFileException, KeyError, OSError, ValueError) as e:
        raise WorkbookError(f"{path.name} could not be read ({e.__class__.__name__}). {CLOSE_EXCEL}") from None
    try:
        sheets = {ws.title: [tuple(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets}
    finally:
        wb.close()
    _CACHE.clear()
    _CACHE[key] = sheets
    return sheets


def clear_cache():
    _CACHE.clear()


def read_sheet_rows(name, path=INSPECTOR_RECORDS):
    """(columns, [(Excel row number, row dict)]) for one sheet. Fully blank rows are skipped."""
    path = Path(path)
    sheets = _load(path)
    if name not in sheets:
        raise WorkbookError(f"{path.name} has no sheet named '{name}'. Sheets found: "
                            f"{', '.join(sheets) or 'none'}. Keep the sheet names sites, inspections, deficiencies.")
    rows = sheets[name]
    header = rows[0] if rows else ()
    columns = [" ".join(str(h).split()) if h is not None else "" for h in header]
    missing = [c for c in REQUIRED.get(name, []) if c not in columns]
    if missing:
        raise WorkbookError(f"{path.name} sheet '{name}' is missing column(s): {', '.join(missing)}. "
                            "Keep the column names in row 1.")
    out = []
    for n, values in enumerate(rows[1:], start=2):
        row = {c: "" for c in columns if c}
        for c, v in zip(columns, values):
            if c:
                row[c] = cell_text(c, v)
        if any(row.values()):
            out.append((n, row))
    return [c for c in columns if c], out


def read_sheet(name, path=INSPECTOR_RECORDS):
    """Rows of one sheet as dicts of strings, in sheet order."""
    return [row for _, row in read_sheet_rows(name, path)[1]]


def check(path=INSPECTOR_RECORDS):
    """Raise WorkbookError if the workbook or any sheet/required column is missing."""
    for name in SHEETS:
        read_sheet_rows(name, path)
