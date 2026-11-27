"""Add / Edit Site tab logic (agent/site_admin.py). Uses temp copies only; real data/ files are never written."""
import shutil
from datetime import datetime

import pytest

from agent import site_admin, swppp
from book_helpers import make_book, sample_book
from config import DATA

NOW = datetime(2026, 11, 25, 9, 30, 0)


@pytest.fixture
def files(tmp_path, monkeypatch):
    """Temp workbook (sample sites T01-T03) and a temp copy of the SWPPP folder; swppp.py reads it too."""
    book = sample_book(tmp_path)
    swppps = tmp_path / "swppps"
    shutil.copytree(DATA / "swppps", swppps)
    monkeypatch.setattr(swppp, "SWPPP_DIR", swppps)
    return {"records_file": book, "swppp_dir": swppps, "backup_dir": tmp_path / "backups"}


def new_site(**kw):
    s = site_admin.new_site_defaults()
    s.update({"site_id": "T04", "name": "SAMPLE Test Yard", "lat": "47.2500", "lon": "-122.4500"})
    s.update(kw)
    return s


CONTROLS = [
    {"control_id": "SF-9", "name": "Silt Fence", "location": "west line",
     "inspect": "undercutting, tears, sediment depth", "maintenance_trigger": "remove sediment at 1/3 height",
     "response": "routine maintenance"},
    {"control_id": "IP-9", "name": "Inlet Protection", "location": "Inlet 1",
     "inspect": "clogged bag", "maintenance_trigger": "", "response": ""},
]


def test_validation_errors(files):
    bad = new_site(site_id="T 4!", name="", lat="95", lon="-200", frequency_option="C",
                   impaired_water="maybe", work_days="Mon-Funday", work_start="7am", work_end="17:00")
    controls = [{"control_id": "sf-1", "name": "", "inspect": ""},
                {"control_id": "SF-2", "name": "A", "inspect": "x"},
                {"control_id": "SF-2", "name": "B", "inspect": "y"}]
    errors = " | ".join(site_admin.validate(bad, controls, files["records_file"]))
    for text in ["letters, digits, and hyphens", "name is required", "Latitude must be between",
                 "Longitude must be between", "Frequency option", "Impaired water must be yes or no",
                 "Work days", "Work start '7am'", "used more than once", "list at least one inspect item"]:
        assert text in errors, text
    # clean_controls upper-cases sf-1, so the format error shows for a truly bad ID
    assert "must be 2-3 capital letters" in " ".join(
        site_admin.validate(new_site(), [{"control_id": "SILT-1", "name": "x", "inspect": "y"}],
                            files["records_file"]))


def test_validation_duplicate_times_and_no_controls(files):
    errors = " | ".join(site_admin.validate(new_site(site_id="T01", work_start="17:00", work_end="07:00"),
                                            [], files["records_file"]))
    assert "already exists" in errors
    assert "must be earlier than work end" in errors
    assert "at least one control" in errors
    assert site_admin.validate(new_site(), CONTROLS, files["records_file"]) == []


def test_errors_save_nothing(files):
    before = files["records_file"].read_bytes()
    errors, backups = site_admin.save_site(new_site(name=""), CONTROLS, "x", now=NOW, **files)
    assert errors and not backups
    assert files["records_file"].read_bytes() == before
    assert not (files["swppp_dir"] / "T04.md").exists()
    assert not files["backup_dir"].exists()


def test_new_site_appended_swppp_written_backup_created(files):
    text = site_admin.build_swppp(new_site(), CONTROLS, {"contacts": "- Pat Lee (DRAFT)"})
    errors, backups = site_admin.save_site(new_site(), CONTROLS, text, now=NOW, **files)
    assert errors == []
    columns, rows = site_admin.read_sites(files["records_file"])
    assert columns == site_admin.SITE_COLUMNS
    assert [r["site_id"] for r in rows] == ["T01", "T02", "T03", "T04"]
    assert rows[-1]["control_ids"] == "SF-9;IP-9"
    assert rows[-1]["work_days"] == "Mon-Fri" and rows[-1]["frequency_option"] == "B"
    assert (files["swppp_dir"] / "T04.md").read_text(encoding="utf-8").startswith(
        "# SWPPP: SAMPLE Test Yard (T04)")
    assert [p.name for p in backups] == ["INSPECTOR_RECORDS_20261125_093000.xlsx"]   # no old T04.md
    assert (files["backup_dir"] / "INSPECTOR_RECORDS_20261125_093000.xlsx").exists()


def test_new_site_keeps_unknown_columns_and_other_rows(files):
    # a sites sheet with an extra column the app doesn't know about
    columns, rows = site_admin.read_sites(files["records_file"])
    make_book(files["records_file"], sites=(columns + ["owner"], [{**r, "owner": "ACME"} for r in rows]))
    columns, rows = site_admin.read_sites(files["records_file"])
    site = {**new_site(), "owner": "Pierce County"}
    errors, _ = site_admin.save_site(site, CONTROLS, site_admin.build_swppp(site, CONTROLS), now=NOW, **files)
    assert errors == []
    columns2, rows2 = site_admin.read_sites(files["records_file"])
    assert columns2 == columns and columns2[-1] == "owner"
    assert rows2[:3] == rows and rows2[3]["owner"] == "Pierce County"


def test_generated_swppp_parses_and_checklist_has_items(files):
    text = site_admin.build_swppp(new_site(), CONTROLS, {"project_description": "Location: Tacoma, WA"})
    site_admin.save_site(new_site(), CONTROLS, text, now=NOW, **files)
    sections = swppp.load_sections("T04")
    assert [(s["number"], s["control_id"]) for s in sections] == [
        ("1.1", ""), ("2.1", ""), ("4.1", "SF-9"), ("4.2", "IP-9")]
    assert sections[2]["title"] == "Silt Fence SF-9"
    assert "Inspect: undercutting, tears, sediment depth" in sections[2]["lines"]
    rows = swppp.checklist("T04", ["SF-9", "IP-9"])
    items = [r["item"] for r in rows if r["control_id"] == "SF-9"]
    assert "Silt Fence SF-9: tears" in items and len(items) == 4     # 3 inspect items + maintenance trigger
    assert any(r["control_id"] == "IP-9" for r in rows)
    assert swppp.threshold_conflicts("T04") == []
    assert site_admin.controls_from_sections(sections) == CONTROLS      # the .md upload path reads it back


def test_uploaded_md_used_and_threshold_warning(files):
    md = ("# SWPPP: SAMPLE Upload Site (T05)\n\n"
          "## 2.1 Inspection Schedule\n- Inspect within 24 hours of a 0.5 in storm\n\n"
          "## 4.1 Wattle WT-1\n- Location: slope\n- Inspect: gaps, sediment\n\n"
          "## 4.2 Check Dam CD-2\n- Inspect: overtopping\n")
    controls = site_admin.controls_from_sections(site_admin.parse_sections(md))
    assert [c["control_id"] for c in controls] == ["WT-1", "CD-2"]
    assert controls[0]["name"] == "Wattle"
    assert site_admin.threshold_conflicts_text(md) and "0.5 in" in site_admin.threshold_conflicts_text(md)[0]
    errors, _ = site_admin.save_site(new_site(site_id="T05"), controls, md, now=NOW, **files)
    assert errors == []
    assert (files["swppp_dir"] / "T05.md").read_text(encoding="utf-8") == md
    _, rows = site_admin.read_sites(files["records_file"])
    assert rows[-1]["control_ids"] == "WT-1;CD-2"
    assert len(swppp.checklist("T05", ["WT-1", "CD-2"])) == 2 + 3
