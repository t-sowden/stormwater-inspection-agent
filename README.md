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

The agent never marks inspections complete, signs reports, or edits inspection records.

## 5. Test

```
uv run --with pytest python -m pytest -q tests
```

All tests should pass.

## 6. Data files

Site data, SWPPPs, the inspection log, and test cases live in `data/` and `tests/`.
Files marked **DRAFT** or **SAMPLE** are placeholders. See `data/DRAFT_DATA_README.md` to replace them.
Settings (station distance, storm threshold, time zone, working hours) are in `config.py`.

## 7. Troubleshooting

| Message | Fix |
| --- | --- |
| `uv is not installed` / `'uv' is not recognized` | Install uv (step 2), then reopen the terminal |
| `Ollama is not running` | Open the Ollama app, then run the launcher again |
| `invalid peer certificate` / `SSLError` | Your network inspects HTTPS. In PowerShell: `setx UV_SYSTEM_CERTS 1`, reopen the terminal |
| `start.bat` won't run by double-click | Open a terminal in the project folder and run `.\start.bat` |
| `trampoline failed` after moving the folder | Delete the `.venv` folder, then run the launcher again |
| Refresh rainfall shows an error | Check your internet connection and the contact email in `config.py` |
| First AI draft is slow | Normal: the model loads on first use (up to about a minute) |
