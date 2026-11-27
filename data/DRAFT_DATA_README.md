# DRAFT placeholder data: how to swap in the final material

Everything marked DRAFT is synthetic filler so the app works end to end. Replace it with the final version
**keeping the same file, sheet, and column names/headings**; no code changes are needed.

## data/INSPECTOR_RECORDS.xlsx (one workbook, three sheets)

Edit it in Excel or on the app's **Site Records** tab. Keep the sheet names and the column names in row 1 exactly as
below; extra columns are kept. Close Excel before saving from the app's **Site Records** or **Add Site** tab.
Times are site-local. Enter them as real Excel dates/times or as text like `2026-11-09 09:00` or `11/9/2026 9:00`
(clock times `07:00` or `7:00 AM`); both work.

| Sheet | What it is | Columns (same as the old CSVs) |
| --- | --- | --- |
| `sites` | Site register | site_id, name, lat, lon, frequency_option (A/B), impaired_water (yes/no), control_ids (`;`-separated), active (yes/no), last_inspection (fallback), work_days (e.g. Mon-Fri), work_start, work_end (HH:MM), works_holidays (yes/no), has_manual_gauge (yes/no; CHECK_GAUGE only fires for "yes") |
| `inspections` | Contractor inspection log | inspection_id, site_id, inspected_at, type (routine/storm), inspector |
| `deficiencies` | Deficiencies found | deficiency_id, site_id, inspection_id, control_id, found_at, description, category, status (open/closed), closed_at. category = routine_maintenance, corrective_no_new_control, or corrective_new_control |

The first nine `sites` columns and every `inspections`/`deficiencies` column are required; if one is missing or
renamed, the app shows an error naming the sheet and column. Saving from the app adds two optional columns at
the end of the sheet it saves, `updated_by` and `updated_at`, and fills them on each row it changes or adds. The old CSVs were moved to `data/legacy_csv/`
when the workbook was made (`uv run python scripts/make_inspector_records.py`; it refuses to overwrite an
existing workbook unless you add `--force`).

## Other files

| File | What it is | Rules to keep |
| --- | --- | --- |
| `data/swppps/<site_id>.md` | One SWPPP per site | Control headings must be `## <number> <name> <CONTROL-ID>`, e.g. `## 4.1 Silt Fence SF-1`. Bullets starting `Inspect:` and `Maintenance trigger:` become checklist items. Control IDs must match `control_ids` in the sites sheet |
| `tests/cases.json` | Test suite for the Verification tab | Each case: id, label (typical/hard/adversarial), type, rule, description, inputs, expected. Copy an existing case of the same type and edit it. Write expected answers from the permit before running |

## Changing records from the app (no AI)

- **Site Records tab:** the Sites, Inspections, and Deficiencies sections show each full sheet.
  - **Log an inspection:** add a row in Inspections; inspection_id gets the next `I-###`.
  - **Close a deficiency:** set status to closed and fill in closed_at.
  - **Edit a site:** change its cells in Sites (site_id can't change; set active to no to retire a site).
  - Rows are never deleted. Each Save writes only that one sheet, after your name is entered in "Saved by".
  - Nothing is saved if any row breaks a rule. For example: a time in the future, closed without closed_at,
    closed_at before found_at, a control not in the site's control_ids, or work start after work end.
- **Add Site tab:** adds a NEW site row and writes `data/swppps/<site_id>.md`. It builds `control_ids` from the
  control table and writes the SWPPP in the `T01.md` heading format (or saves an uploaded `.md` as is).
  Existing sites are edited on Site Records.

Every save keeps the other sheets, the column order, cell formats, and extra columns. Before each save, the
whole workbook is copied to `data/backups/INSPECTOR_RECORDS_<YYYYMMDD_HHMMSS>.xlsx` (not tracked by Git). To undo
a save, copy the backup back over `data/INSPECTOR_RECORDS.xlsx`. If the workbook is open in Excel, nothing is
saved and the app asks you to close it. The app never touches the test cases.

After swapping: run `uv run --with pytest python -m pytest -q tests`, or click **Run test suite** on the
Verification tab, and record failures in `data/failure_register.csv`.
