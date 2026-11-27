"""Combine data/sites.csv, data/inspections.csv and data/deficiencies.csv into data/INSPECTOR_RECORDS.xlsx.

Run once from the project folder:
    uv run python scripts/make_inspector_records.py            (refuses to overwrite an existing workbook)
    uv run python scripts/make_inspector_records.py --force    (replace it)

Sheets "sites", "inspections", "deficiencies" keep the CSV column names and order. Date-times become real
Excel date-times (yyyy-mm-dd hh:mm), work_start/work_end real Excel times (hh:mm), everything else text.
The workbook is read back and compared with the CSVs; only if they match are the CSVs moved to
data/legacy_csv/, so there is one source of truth.
"""
import argparse
import csv
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openpyxl import Workbook                                        # noqa: E402
from openpyxl.styles import Font                                     # noqa: E402

from agent import workbook                                           # noqa: E402
from config import DATA                                              # noqa: E402

SHEET_ORDER = ["sites", "inspections", "deficiencies"]


def read_csv(path):
    """(columns, rows) from a CSV, values stripped."""
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = [{k: (v or "").strip() for k, v in r.items() if k is not None} for r in reader]
        return list(reader.fieldnames or []), rows


def format_sheet(ws, columns, rows):
    """Bold frozen header and roughly fitted column widths."""
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    for i, col in enumerate(columns, start=1):
        longest = max([len(col)] + [len(workbook.cell_text(col, r.get(col, ""))) for r in rows])
        ws.column_dimensions[ws.cell(1, i).column_letter].width = min(max(longest + 2, 8), 60)


def write_row(ws, row_number, columns, row):
    """Write one row of app strings: real date-times/times for time columns, text for the rest."""
    for i, col in enumerate(columns, start=1):
        value, fmt = workbook.cell_value(col, row.get(col, ""))
        cell = ws.cell(row_number, i, value)
        if fmt:
            cell.number_format = fmt


def build_workbook(sheets, path):
    """Write a new workbook. sheets: {name: (columns, rows)} for sites, inspections, deficiencies."""
    wb = Workbook()
    wb.remove(wb.active)
    for name in SHEET_ORDER:
        columns, rows = sheets[name]
        ws = wb.create_sheet(name)
        ws.append(columns)
        for n, row in enumerate(rows, start=2):
            write_row(ws, n, columns, row)
        format_sheet(ws, columns, rows)
    path = Path(path)
    tmp = path.with_name(path.stem + ".tmp.xlsx")
    wb.save(tmp)
    tmp.replace(path)
    workbook.clear_cache()
    return path


def expected_rows(columns, rows):
    """What read_sheet should return for these CSV rows (times in the standard format)."""
    return [{c: workbook.cell_text(c, r.get(c, "")) for c in columns} for r in rows
            if any((r.get(c) or "").strip() for c in columns)]


def migrate(data_dir=DATA, force=False, move=True):
    """CSVs in data_dir -> data_dir/INSPECTOR_RECORDS.xlsx. Returns (workbook path, moved CSV paths)."""
    data_dir = Path(data_dir)
    out = data_dir / "INSPECTOR_RECORDS.xlsx"
    csvs = {name: data_dir / f"{name}.csv" for name in SHEET_ORDER}
    missing = [p.name for p in csvs.values() if not p.exists()]
    if missing:
        raise SystemExit(f"Missing {', '.join(missing)} in {data_dir}. Nothing written.")
    if out.exists() and not force:
        raise SystemExit(f"{out} already exists. Nothing written. Use --force to replace it.")

    sheets = {name: read_csv(path) for name, path in csvs.items()}
    build_workbook(sheets, out)

    for name, (columns, rows) in sheets.items():           # read back and compare before moving anything
        got_columns, got = workbook.read_sheet_rows(name, out)
        got = [r for _, r in got]
        if got_columns != columns or got != expected_rows(columns, rows):
            raise SystemExit(f"Check failed: sheet '{name}' does not match {name}.csv. CSVs left in place.")

    moved = []
    if move:
        legacy = data_dir / "legacy_csv"
        legacy.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for path in csvs.values():
            target = legacy / path.name
            if target.exists():
                target = legacy / f"{path.stem}_{stamp}{path.suffix}"
            shutil.move(str(path), str(target))
            moved.append(target)
    return out, moved


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="replace an existing INSPECTOR_RECORDS.xlsx")
    parser.add_argument("--data-dir", default=str(DATA), help="folder with the three CSVs (default: data/)")
    args = parser.parse_args(argv)
    out, moved = migrate(args.data_dir, force=args.force)
    print(f"Wrote {out}")
    for path in moved:
        print(f"Moved CSV to {path}")


if __name__ == "__main__":
    main()
