# Construction Stormwater Inspection Agent

CIVE 580C8, Remote Team D. A free, local dashboard that tracks rainfall, computes EPA 2022 CGP
inspection and corrective-action deadlines, and drafts inspection reports for the inspector to review.
Everything runs on your own computer. The only internet use is the **Refresh rainfall** button (NOAA).

## 1. Requirements

| Item | Minimum |
| --- | --- |
| Operating system | Windows 10+, macOS 14+, or Linux |
| Memory | 8 GB RAM |
| Free disk space | about 4 GB (AI model + Python packages) |

## 2. Install (once per computer)

1. **Ollama** (local AI): download from https://ollama.com and install. Open the Ollama app.
2. **uv** (installs Python and all packages automatically):
   - Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
   - Mac/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - Close and reopen the terminal afterwards.
3. **Get the project**: on GitHub, click **Code > Download ZIP** and unzip it, or clone it with Git.
   Put it in a plain folder (not OneDrive/Dropbox), e.g. `C:\Projects\stormwater-inspection-agent`.

You do **not** need to install Python separately.

## 3. Run

- **Windows:** double-click `start.bat`, or run `.\start.bat` in a terminal opened in the project folder.
- **Mac/Linux:** run `./start.sh` in the project folder.

The first run downloads the AI model (2 GB) and Python packages, which takes a few minutes.
Your browser then opens the dashboard at `http://localhost:8501`. Keep the terminal window open;
closing it stops the app.

## 4. Use

| Tab | What it does |
| --- | --- |
| **Storm Triage** | Click **Refresh rainfall**. Shows each site's next due inspection, station and distance, open fixes, and flags |
| **Site Records** | Pick a site for its last inspection, next due date, open deficiencies, and a SWPPP-cited checklist. Below that, view and edit the inspector records (see below) |
| **Draft Report** | Enter findings, click **Draft report**. Python sets every deadline; the local AI writes the wording; download the draft |
| **Verification** | Click **Run test suite** to see pass rates by category |
| **Add Site** | Add a new site and its SWPPP (see below) |

The agent (and its AI) never marks inspections complete, signs reports, or changes inspection records on its own.
Records change only when an inspector clicks Save on **Site Records** or **Add Site**. Checklist tick boxes
are a field aid only and are never saved.

### Site Records tab: editing the inspector records

Below the checklist, **Inspector records (INSPECTOR_RECORDS.xlsx)** has three collapsed sections, **Sites**,
**Inspections**, and **Deficiencies**. Each one shows the whole sheet with the same columns as in Excel.
Dates use a date picker, and fixed choices (A/B, yes/no, routine/storm, category, status, site ID) are dropdowns.

- **Log an inspection:** open **Inspections** and add a row with **+** below the table. Pick the site, then
  enter inspected_at, type, and inspector. Leave inspection_id blank; it gets the next `I-###`. Due dates on
  Storm Triage then count from this inspection.
- **Close a deficiency:** open **Deficiencies**, find the row, set status to **closed**, and enter closed_at
  (when the fix was finished). It then drops out of the open fixes. Log a new deficiency the same way as an
  inspection; it gets the next `D-###`.
- **Edit a site:** open **Sites** and change the cells. site_id can't be changed. To retire a site, set
  active to **no**. New sites are added on the **Add Site** tab.
- **Save:** type your name in **Saved by**. Tick **Show changes** to review the added rows and changed cells
  (old -> new), then click **Save sites** / **Save inspections** / **Save deficiencies**.
  - Each Save writes only that sheet and stamps each changed or added row with updated_by and updated_at.
  - Storm Triage and the metrics update immediately.
- **Rows can't be deleted.** A save that would remove a row is refused; correct the values instead.
- **Before every save, the whole workbook is copied** to `data/backups/INSPECTOR_RECORDS_<date>_<time>.xlsx`.
  To undo a save, copy a backup back over `data/INSPECTOR_RECORDS.xlsx`.
- **Close `INSPECTOR_RECORDS.xlsx` in Excel before saving.** If it's open, nothing is saved and you're asked
  to close it.
- **Nothing is saved if anything is wrong.** Every problem is listed in plain English, for example: a time in
  the future, a closed deficiency with no closed_at, or a control that isn't one of the site's controls.

### Add Site tab

1. Fill in the site details (the site ID must be new), the control measures table (one row per control, e.g.
   `SF-1`; Inspect items comma-separated), and any optional SWPPP sections (one bullet per line). Or upload a
   finished SWPPP `.md`.
2. Check the preview: the row for the `sites` sheet, the SWPPP text, the controls found, and any problems.
3. **Close `INSPECTOR_RECORDS.xlsx` in Excel**, then click **Save site**. Nothing is saved if anything is wrong
   or the workbook is open. The workbook is first copied to `data/backups/`.
4. Click **Refresh rainfall** on Storm Triage to assign the new site a weather station.

Plain Python, no AI. It adds one row to the `sites` sheet of `data/INSPECTOR_RECORDS.xlsx` (the other sheets are
kept as they are) and writes `data/swppps/<site_id>.md`. To change an existing site, use **Site Records**.

## 5. Test

```
uv run --with pytest python -m pytest -q tests
```

All tests should pass. The 32 cases are listed in `tests/TEST_CASES.md`.

## 6. Data files

Sites, the inspection log, and the deficiency list are in **one Excel workbook, `data/INSPECTOR_RECORDS.xlsx`**,
with three sheets: `sites`, `inspections`, `deficiencies`.

- Edit `INSPECTOR_RECORDS.xlsx` in Excel. Keep the sheet names and the column names in row 1.
- Dates and times can be real Excel dates/times or text (`2026-11-09 09:00` or `11/9/2026 9:00`).
- The app can read the workbook while Excel has it open (press F5 after saving in Excel to reload).
- Close Excel before saving from the **Site Records** or **Add Site** tab.
- If a sheet or column is missing or renamed, Storm Triage shows an error naming it.

SWPPPs are in `data/swppps/`; test cases are in `tests/`. The old CSVs are kept in `data/legacy_csv/` for
reference only; the app no longer reads them. Files marked **DRAFT** or **SAMPLE** are placeholders. See
`data/DRAFT_DATA_README.md` to replace them.
Settings (station distance, storm threshold, time zone, working hours) are in `config.py`.

## 7. Offline demo (saved data)

Rainfall is cached in `data/rain_cache/`. Without a refresh, old data is flagged `DATA_LATE`.
To demo with saved data, tick **Replay: judge everything as of the last refresh** in the sidebar.
DATA_LATE, OVERDUE, and due dates are then computed as of the last refresh time.

## 8. Known limitations (v1)

| Limitation | Effect |
| --- | --- |
| A remotely readable site rain gauge does not override NOAA (R8) | The agent always uses the nearest ASOS station. Enter a manual gauge reading on the Draft Report tab; a reading of 0.25 in or more with no station trigger is flagged `POSSIBLE_MISSED_INSPECTION` |
| No check for a station without a working rain sensor | A station that never sends a precipitation group looks "dry" every hour. Compare with a nearby station if a site's rain looks too low |
| R7 manager setting is not stored | When `INTERPRETATION_REQUIRED` shows, both deadlines are listed; the manager picks one |
| R12 "infeasible" is not a field in the log | Only R10 (routine) shows the 7-day infeasible deadline |
| R11 counts repeats by control ID only | The log has no location column, so "same location" and "same fix" are not checked |
| Validator blocks any word starting with "certif" | Product names such as "certified weed-free straw" are rejected. Kept on purpose: safer |
| Validator uses word patterns | New phrasings can slip through; failures go to `data/failure_register.csv` |
| Contractor inspection form | Inspections and deficiencies are logged by an inspector in the Site Records tab (or in Excel). The agent never adds or changes them on its own |

## 9. Troubleshooting

| Message | Fix |
| --- | --- |
| `INSPECTOR_RECORDS.xlsx is open in Excel. Close it and click Save again.` | Close the workbook in Excel, then click Save again. Nothing was saved |
| `Close INSPECTOR_RECORDS.xlsx in Excel and press F5.` | The workbook couldn't be read (often mid-save in Excel). Close it, then press F5 |
| `... has no sheet named ...` / `... is missing column(s) ...` | Rename the sheet or row-1 column back to the name shown (see `data/DRAFT_DATA_README.md`) |
| `uv is not installed` / `'uv' is not recognized` after installation | Reopen PowerShell, or run `$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"`, then run the launcher again. |
| `Failed to spawn: streamlit` / `Application Control policy has blocked this file (os error 4551)` | Wait a few seconds, then rerun `.\start.bat`. If the error persists, contact your IT administrator. Reinstallation is generally unnecessary. |
| `Ollama is not running` | Open the Ollama app, then run the launcher again |
| `invalid peer certificate` / `SSLError` | Your network inspects HTTPS. In PowerShell: `setx UV_SYSTEM_CERTS 1`, reopen the terminal |
| `start.bat` won't run by double-click | Open a terminal in the project folder and run `.\start.bat` |
| `trampoline failed` after moving the folder | Delete the `.venv` folder, then run the launcher again |
| Refresh rainfall shows an error | Check your internet connection and the contact email in `config.py` |
| First AI draft is slow | Normal: the model loads on first use (up to about a minute) |
