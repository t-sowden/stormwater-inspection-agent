"""A site with no logged inspection must not break the Storm Triage table or the site context."""
from datetime import datetime, timezone

import pandas as pd
import pytest

from config import ROOT

NOW = datetime(2026, 11, 25, 18, 0, tzinfo=timezone.utc)


def app_helpers():
    """Run only the helper code of app.py (everything above the page layout), not the Streamlit page."""
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    helpers = source.split("# ---------- Page ----------")[0]
    ns = {"__name__": "app_helpers"}
    exec(compile(helpers, "app.py", "exec"), ns)
    ns["load_cache"] = lambda station_id: []                 # no saved rain needed
    return ns


def new_site():
    return pd.DataFrame([{"site_id": "T99", "name": "SAMPLE Never Inspected", "lat": 47.25, "lon": -122.45,
                          "frequency_option": "B", "impaired_water": "no", "control_ids": "SF-1",
                          "active": "yes", "last_inspection": "", "work_days": "Mon-Fri",
                          "work_start": "07:00", "work_end": "17:00", "works_holidays": "no",
                          "has_manual_gauge": "no"}])


def stations():
    return pd.DataFrame([{"site_id": "T99", "station_id": "KTIW", "station_name": "Tacoma Narrows",
                          "station_lat": 47.27, "station_lon": -122.58, "distance_mi": 6.3,
                          "station_flags": ""}]).set_index("site_id")


OVERDUE_FIX = {"deficiency_id": "D99", "site_id": "T99", "inspection_id": "", "control_id": "SF-1",
               "found_at": "2026-10-20 09:00", "description": "Sediment at 1/2 fence height",
               "category": "routine_maintenance", "status": "open", "closed_at": ""}


@pytest.mark.parametrize("fixes, priority", [([], "CHECK DATA"), ([OVERDUE_FIX], "OVERDUE")],
                         ids=["no-overdue-fix", "overdue-fix"])
def test_triage_and_context_without_last_inspection(monkeypatch, fixes, priority):
    app = app_helpers()
    monkeypatch.setattr(app["records"], "inspections", lambda site_id=None: [])
    monkeypatch.setattr(app["records"], "deficiencies", lambda site_id=None: list(fixes))
    table, problems = app["build_triage"](new_site(), stations(), NOW)
    assert problems == []
    row = table.iloc[0]
    assert row["Priority"] == priority
    assert row["Next due"] == "First inspection needed"
    assert row["Due for"] == "Initial inspection"
    assert "NO_INSPECTION_LOGGED" in row["Flags"]
    assert ("OVERDUE" in row["Flags"]) == bool(fixes)
    assert row["Station"] == "KTIW" and row["Distance (mi)"] == 6.3 and row["Open fixes"] == len(fixes)

    ctx = app["site_context"](new_site().iloc[0], stations(), NOW)
    assert ctx["items"] == [] and ctx["site"]["last_inspection"] == ""
