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
| **Site Checklist** | Pick a site for a SWPPP-cited inspection checklist and its open deficiencies |
| **Draft Report** | Enter findings, click **Draft report**. Python sets every deadline; the local AI writes the wording; download the draft |
| **Verification** | Click **Run test suite** to see pass rates by category |
| **Add / Edit Site** | Add a site or edit one (see below) |

The agent never marks inspections complete, signs reports, or edits inspection records.

### Add / Edit Site tab

1. Pick **New site**, or an existing site ID to load its current values (the site ID can't be changed).
2. Fill in the site details, the control measures table (one row per control, e.g. `SF-1`; Inspect items
   comma-separated), and any optional SWPPP sections (one bullet per line). Or upload a finished SWPPP `.md`.
3. Check the preview: the `sites.csv` row, the SWPPP text, the controls found, and any problems.
4. Click **Save site**. Nothing is saved if anything is wrong. Both files are first copied to `data/backups/`.
5. Click **Refresh rainfall** on Storm Triage to assign the new site a weather station.

Plain Python, no AI. It writes only `data/sites.csv` and `data/swppps/<site_id>.md`.

## 5. Test

```
uv run --with pytest python -m pytest -q tests
```

All tests should pass. The 32 cases are listed in `tests/TEST_CASES.md`.

## 6. Data files

Site data, SWPPPs, the inspection log, and test cases live in `data/` and `tests/`.
Files marked **DRAFT** or **SAMPLE** are placeholders. See `data/DRAFT_DATA_README.md` to replace them.
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
| Contractor inspection form | The agent reads `data/inspections.csv` and `data/deficiencies.csv` only; it never writes them |

## 9. Troubleshooting

| Message | Fix |
| --- | --- |
| `uv is not installed` / `'uv' is not recognized` after installation | Reopen PowerShell, or run `$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"`, then run the launcher again. |
| `Failed to spawn: streamlit` / `Application Control policy has blocked this file (os error 4551)` | Wait a few seconds, then rerun `.\start.bat`. If the error persists, contact your IT administrator. Reinstallation is generally unnecessary. |
| `Ollama is not running` | Open the Ollama app, then run the launcher again |
| `invalid peer certificate` / `SSLError` | Your network inspects HTTPS. In PowerShell: `setx UV_SYSTEM_CERTS 1`, reopen the terminal |
| `start.bat` won't run by double-click | Open a terminal in the project folder and run `.\start.bat` |
| `trampoline failed` after moving the folder | Delete the `.venv` folder, then run the launcher again |
| Refresh rainfall shows an error | Check your internet connection and the contact email in `config.py` |
| First AI draft is slow | Normal: the model loads on first use (up to about a minute) |
