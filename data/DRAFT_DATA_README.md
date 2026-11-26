# DRAFT placeholder data: how to swap in the final material

Everything marked DRAFT is synthetic filler so the app works end to end. Replace a file with the
final version **using the same file name and the same columns/headings**; no code changes are needed.

| File | What it is | Rules to keep |
| --- | --- | --- |
| `data/sites.csv` | Site register | Columns: site_id, name, lat, lon, frequency_option (A/B), impaired_water (yes/no), control_ids (`;`-separated), active (yes/no), last_inspection (fallback), work_days (e.g. Mon-Fri), work_start, work_end (HH:MM), works_holidays (yes/no), has_manual_gauge (yes/no; CHECK_GAUGE only fires for "yes") |
| `data/swppps/<site_id>.md` | One SWPPP per site | Control headings must be `## <number> <name> <CONTROL-ID>`, e.g. `## 4.1 Silt Fence SF-1`. Bullets starting `Inspect:` and `Maintenance trigger:` become checklist items. Control IDs must match `control_ids` in sites.csv |
| `data/inspections.csv` | Contractor inspection log (read-only to the app) | Columns: inspection_id, site_id, inspected_at (YYYY-MM-DD HH:MM, site-local), type (routine/storm), inspector |
| `data/deficiencies.csv` | Deficiencies found (read-only to the app) | Columns: deficiency_id, site_id, inspection_id, control_id, found_at, description, category, status (open/closed), closed_at. category = routine_maintenance, corrective_no_new_control, or corrective_new_control |
| `tests/cases.json` | Test suite for the Verification tab | Each case: id, label (typical/hard/adversarial), type, rule, description, inputs, expected. Copy an existing case of the same type and edit it. Write expected answers from the permit before running |

## Add / Edit Site tab

The **Add / Edit Site** tab is the other way to change `data/sites.csv` and `data/swppps/<site_id>.md`.
It keeps the column order and any extra columns, builds `control_ids` from the control table, and writes the
SWPPP in the `T01.md` heading format (or saves an uploaded `.md` as is). Before each save, the old files are
copied to `data/backups/<name>_<YYYYMMDD_HHMMSS>.<ext>` (not tracked by Git). To undo a save, copy the backup
back over the file. The tab never touches the inspection log, the deficiency list, or the test cases.

After swapping: run `uv run --with pytest python -m pytest -q tests`, or click **Run test suite** on the
Verification tab, and record failures in `data/failure_register.csv`.
