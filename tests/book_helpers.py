"""Build temp INSPECTOR_RECORDS.xlsx workbooks for tests. Never touches data/.

SAMPLE_* are copies of the three CSVs as they were just before the move to the workbook
(times already in Excel's US style, as Excel had re-saved them).
"""
import csv
import importlib.util
from pathlib import Path

from openpyxl import Workbook

from agent import workbook
from config import ROOT

_spec = importlib.util.spec_from_file_location("make_inspector_records",
                                               ROOT / "scripts" / "make_inspector_records.py")
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)

SAMPLE_CSVS = {
    "sites": """site_id,name,lat,lon,frequency_option,impaired_water,control_ids,active,last_inspection,work_days,work_start,work_end,works_holidays,has_manual_gauge
T01,SAMPLE Tideflats Logistics Yard,47.2690,-122.4125,B,yes,SF-1;IP-2;CB-1,yes,2026-11-16 09:00,Mon-Fri,07:00,17:00,no,yes
T02,SAMPLE South Tacoma Way Apartments,47.2140,-122.4740,B,no,SF-2;IP-1,yes,2026-11-13 10:00,Mon-Fri,07:00,17:00,no,no
T03,SAMPLE Point Defiance Trailhead Parking,47.3030,-122.5160,A,no,SF-3,yes,2026-11-17 13:30,Mon-Sat,07:00,15:00,no,yes
""",
    "inspections": """inspection_id,site_id,inspected_at,type,inspector
I-001,T01,11/9/2026 9:00,routine,J. Rivera (DRAFT)
I-002,T01,11/16/2026 9:00,routine,J. Rivera (DRAFT)
I-003,T02,11/13/2026 10:00,routine,J. Rivera (DRAFT)
I-004,T03,11/10/2026 13:30,routine,J. Rivera (DRAFT)
I-005,T03,11/17/2026 13:30,routine,J. Rivera (DRAFT)
I-001,T01,11/25/2026 9:00,routine,J. Rivera (DRAFT)
I-003,T02,11/25/2026 11:00,routine,J. Rivera (DRAFT)
I-004,T03,11/25/2026 15:30,routine,J. Rivera (DRAFT)
""",
    "deficiencies": """deficiency_id,site_id,inspection_id,control_id,found_at,description,category,status,closed_at
D-001,T01,I-001,SF-1,11/9/2026 9:30,Sediment at 1/3 fence height along north line (DRAFT),routine_maintenance,closed,11/10/2026 14:00
D-002,T01,I-002,SF-1,11/16/2026 9:20,Sediment at 1/3 fence height along north line again (DRAFT),routine_maintenance,closed,11/17/2026 11:00
D-003,T01,I-002,IP-2,11/16/2026 9:40,Filter bag torn at Inlet 3 (DRAFT),corrective_new_control,closed,11/25/2026 9:00
D-004,T02,I-003,SF-2,11/13/2026 10:20,Silt fence undercut near southeast corner (DRAFT),corrective_no_new_control,closed,11/25/2026 11:00
D-005,T03,I-005,SF-3,11/17/2026 13:45,Minor sediment buildup at west end (DRAFT),routine_maintenance,closed,11/25/2026 14:00
""",
}


def write_sample_csvs(folder):
    """Write the three sample CSVs (utf-8-sig, like Excel saves them) into folder."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in SAMPLE_CSVS.items():
        (folder / f"{name}.csv").write_text(text, encoding="utf-8-sig")
    return folder


def read_csv(path):
    return migration.read_csv(path)


def sample_book(folder):
    """A workbook made from the sample CSVs by the migration script (CSVs left in folder/src)."""
    src = write_sample_csvs(Path(folder) / "src")
    path, _ = migration.migrate(src, move=False)
    return path


def raw_book(path, **sheets):
    """Workbook with cell values written exactly as given (datetime objects, US text, numbers...).

    sheets: {name: (columns, [list of cell values per row])}; sheets not given are empty.
    """
    wb = Workbook()
    wb.remove(wb.active)
    for name, cols in workbook.SHEETS.items():
        columns, rows = sheets.get(name, (cols, []))
        ws = wb.create_sheet(name)
        ws.append(columns)
        for r in rows:
            ws.append(r)
    wb.save(path)
    workbook.clear_cache()
    return Path(path)


def make_book(path, **sheets):
    """Workbook with the given sheets {name: (columns, rows)}; sheets not given are empty."""
    full = {name: sheets.get(name, (cols, [])) for name, cols in workbook.SHEETS.items()}
    return migration.build_workbook(full, path)
