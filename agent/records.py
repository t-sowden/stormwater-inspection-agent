"""Read the contractor's inspection log and deficiency list. READ-ONLY: this module never writes them.

Files (Alex replaces the DRAFT rows with final synthetic data; keep the column names):
  data/inspections.csv   inspection_id, site_id, inspected_at, type, inspector
  data/deficiencies.csv  deficiency_id, site_id, inspection_id, control_id, found_at,
                         description, category, status, closed_at
Times are site-local, written as YYYY-MM-DD HH:MM.
"""
import csv
from datetime import datetime

from config import DATA

INSPECTIONS_FILE = DATA / "inspections.csv"
DEFICIENCIES_FILE = DATA / "deficiencies.csv"


def _read(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def inspections(site_id=None):
    rows = _read(INSPECTIONS_FILE)
    return [r for r in rows if site_id is None or r["site_id"] == site_id]


def deficiencies(site_id=None):
    rows = _read(DEFICIENCIES_FILE)
    return [r for r in rows if site_id is None or r["site_id"] == site_id]


def last_inspection(site_id, fallback=""):
    """Latest inspected_at for the site from the log; falls back to sites.csv last_inspection."""
    times = [r["inspected_at"] for r in inspections(site_id) if r.get("inspected_at")]
    if times:
        return max(times, key=lambda t: datetime.fromisoformat(t))
    return fallback
