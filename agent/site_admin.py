"""Add or edit a site: validate, build its SWPPP markdown, back up, and save. Plain Python, no AI.

Used by the "Add / Edit Site" tab. Writes only two things:
  data/sites.csv            one row per site (column order and unknown columns are kept)
  data/swppps/<site_id>.md  the site's SWPPP, in the same heading format swppp.py reads
Before any write, the current file is copied to data/backups/<name>_<YYYYMMDD_HHMMSS>.<ext>.
Every function takes its file paths as parameters so tests can point them at a temp folder.
"""
import csv
import re
import shutil
from datetime import datetime, time

from agent import swppp
from agent.scheduler import parse_work_days
from config import (DATA, DEFAULT_WORK_DAYS, DEFAULT_WORK_END, DEFAULT_WORK_START,
                    SITES_FILE, STORM_THRESHOLD_IN)

SWPPP_DIR = swppp.SWPPP_DIR
BACKUP_DIR = DATA / "backups"

SITE_COLUMNS = ["site_id", "name", "lat", "lon", "frequency_option", "impaired_water", "control_ids",
                "active", "last_inspection", "work_days", "work_start", "work_end", "works_holidays",
                "has_manual_gauge"]
YES_NO_FIELDS = ["impaired_water", "active", "works_holidays", "has_manual_gauge"]
CONTROL_FIELDS = ["control_id", "name", "location", "inspect", "maintenance_trigger", "response"]
# Bullet label in the SWPPP -> control table column
CONTROL_BULLETS = [("Location", "location"), ("Inspect", "inspect"),
                   ("Maintenance trigger", "maintenance_trigger"), ("Response", "response")]
# Non-control sections: key -> (number, heading)
TEXT_SECTIONS = {
    "project_description": ("1.1", "Project Description"),
    "inspection_schedule": ("2.1", "Inspection Schedule"),
    "contacts": ("3.1", "Contacts"),
    "corrective_procedure": ("5.1", "Corrective Action Procedure"),
}
SITE_ID_RE = re.compile(r"^[A-Za-z0-9-]+$")
CONTROL_ID_RE = re.compile(r"^[A-Z]{2,3}-\d+$")
HHMM_RE = re.compile(r"^\d{2}:\d{2}$")


# ---------- Reading ----------
def read_sites(sites_file=SITES_FILE):
    """(columns, rows) from sites.csv. Rows are dicts of stripped strings, in file order."""
    if not sites_file.exists():
        return list(SITE_COLUMNS), []
    with sites_file.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = [{k: (v or "").strip() for k, v in row.items() if k is not None} for row in reader]
        columns = list(reader.fieldnames or SITE_COLUMNS)
    return columns, rows


def new_site_defaults(columns=SITE_COLUMNS):
    """Blank row for a new site with the agreed defaults (unknown columns blank)."""
    row = {c: "" for c in columns}
    row.update({"frequency_option": "B", "impaired_water": "no", "active": "yes",
                "work_days": DEFAULT_WORK_DAYS, "work_start": DEFAULT_WORK_START,
                "work_end": DEFAULT_WORK_END, "works_holidays": "no", "has_manual_gauge": "no",
                "last_inspection": ""})
    return row


def parse_sections(text):
    """Sections from SWPPP markdown text, using the same HEADING / CONTROL_ID rules as swppp.load_sections."""
    sections, current = [], None
    for raw in text.splitlines():
        m = swppp.HEADING.match(raw)
        if m:
            number, title = m.group(1), m.group(2)
            cid = swppp.CONTROL_ID.search(title)
            current = {"number": number, "title": title,
                       "control_id": cid.group(1) if cid else "", "lines": []}
            sections.append(current)
        elif current is not None and raw.strip().startswith("-"):
            current["lines"].append(raw.strip()[1:].strip())
    return sections


def controls_from_sections(sections):
    """Control table rows from SWPPP sections (those whose heading ends in a control ID)."""
    rows = []
    for s in sections:
        if not s["control_id"]:
            continue
        name = s["title"][: -len(s["control_id"])].strip()
        row = {"control_id": s["control_id"], "name": name, "location": "", "inspect": "",
               "maintenance_trigger": "", "response": ""}
        for line in s["lines"]:
            label, colon, value = line.partition(":")
            for bullet, field in CONTROL_BULLETS:
                if colon and label.strip().lower() == bullet.lower():
                    row[field] = value.strip()
        rows.append(row)
    return rows


def text_sections_from(sections):
    """{key: [lines]} for the non-control sections (project description, schedule, contacts, procedure)."""
    out = {key: [] for key in TEXT_SECTIONS}
    for s in sections:
        if s["control_id"]:
            continue
        title = s["title"].strip().lower()
        for key, (_, heading) in TEXT_SECTIONS.items():
            if title == heading.lower():
                out[key] = list(s["lines"])
    return out


# ---------- Cleaning ----------
def _cell(value):
    """Table cell -> one-line string ('' for None/NaN)."""
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return " ".join(str(value).split())


def clean_controls(rows):
    """Normalize data_editor rows: strings only, single line, fully blank rows dropped."""
    out = []
    for r in rows:
        row = {f: _cell(r.get(f)) for f in CONTROL_FIELDS}
        row["control_id"] = row["control_id"].upper()
        if any(row.values()):
            out.append(row)
    return out


def clean_lines(text_or_lines):
    """Text area (one bullet per line) or list -> non-blank lines without leading bullet marks."""
    lines = text_or_lines.splitlines() if isinstance(text_or_lines, str) else list(text_or_lines or [])
    out = []
    for line in lines:
        line = str(line).strip().lstrip("-*•").strip()
        if line:
            out.append(line)
    return out


def inspect_items(text):
    return [x.strip() for x in str(text).split(",") if x.strip()]


# ---------- SWPPP markdown ----------
def default_schedule_lines(site):
    """Inspection schedule bullets when none are typed, from frequency option and impaired water."""
    impaired = str(site.get("impaired_water", "")).lower() == "yes"
    if impaired:
        return [f"Frequency: at least every 7 calendar days and within 24 hours of a {STORM_THRESHOLD_IN} in "
                "storm (impaired receiving water)"]
    if str(site.get("frequency_option", "B")).upper() == "A":
        return ["Frequency: at least every 7 calendar days (Option A)"]
    return [f"Frequency: at least every 14 calendar days and within 24 hours of a {STORM_THRESHOLD_IN} in "
            "storm (Option B)"]


def build_swppp(site, controls, text_sections=None):
    """SWPPP markdown in the data/swppps/T01.md format."""
    ts = {k: clean_lines(v) for k, v in (text_sections or {}).items()}
    out = [f"# SWPPP: {site.get('name', '').strip()} ({site.get('site_id', '').strip()})", ""]

    def section(number, heading, lines):
        out.append(f"## {number} {heading}")
        out.extend(f"- {line}" for line in lines)
        out.append("")

    section("1.1", "Project Description", ts.get("project_description") or [])
    section("2.1", "Inspection Schedule", ts.get("inspection_schedule") or default_schedule_lines(site))
    if ts.get("contacts"):
        section("3.1", "Contacts", ts["contacts"])
    for n, c in enumerate(clean_controls(controls), start=1):
        section(f"4.{n}", f"{c['name']} {c['control_id']}",
                [f"{label}: {c[field]}" for label, field in CONTROL_BULLETS])
    if ts.get("corrective_procedure"):
        section("5.1", "Corrective Action Procedure", ts["corrective_procedure"])
    return "\n".join(out).rstrip() + "\n"


def threshold_conflicts_text(text):
    """Same check as swppp.threshold_conflicts, on markdown text that is not saved yet."""
    warnings = []
    for s in parse_sections(text):
        for line in s["lines"]:
            if re.search(r"storm|rain", line, re.I):
                for value in swppp.INCHES.findall(line):
                    if abs(float(value) - STORM_THRESHOLD_IN) > 1e-9:
                        warnings.append(f"SWPPP §{s['number']} states a {value} in storm threshold; "
                                        f"the permit's {STORM_THRESHOLD_IN} in governs and is used.")
    return warnings


def control_id_problems(controls):
    """Plain-English problems with control IDs (format and duplicates)."""
    problems, seen = [], set()
    for i, c in enumerate(controls, start=1):
        cid = c.get("control_id", "")
        if not cid:
            problems.append(f"Control row {i}: control ID is missing.")
        elif not CONTROL_ID_RE.match(cid):
            problems.append(f"Control row {i}: control ID '{cid}' must be 2-3 capital letters, a hyphen, "
                            "and a number (e.g. SF-1).")
        elif cid in seen:
            problems.append(f"Control ID '{cid}' is used more than once.")
        seen.add(cid)
    return problems


# ---------- Validation ----------
def _is_hhmm(value):
    if not HHMM_RE.match(value):
        return False
    try:
        time.fromisoformat(value)
        return True
    except ValueError:
        return False


def validate(site, controls, is_new, sites_file=SITES_FILE):
    """Plain-English errors; an empty list means the site can be saved."""
    errors = []
    s = {k: str(v if v is not None else "").strip() for k, v in site.items()}
    sid = s.get("site_id", "")
    _, rows = read_sites(sites_file)
    existing = {r.get("site_id", "").lower() for r in rows}

    if not sid:
        errors.append("Site ID is required.")
    elif not SITE_ID_RE.match(sid):
        errors.append(f"Site ID '{sid}' may only contain letters, digits, and hyphens.")
    elif is_new and sid.lower() in existing:
        errors.append(f"Site ID '{sid}' already exists. Pick it in the selector to edit it instead.")
    elif not is_new and sid.lower() not in existing:
        errors.append(f"Site ID '{sid}' is not in sites.csv, so it cannot be edited.")
    if not s.get("name"):
        errors.append("Site name is required.")

    for field, low, high in (("lat", -90, 90), ("lon", -180, 180)):
        label = "Latitude" if field == "lat" else "Longitude"
        try:
            value = float(s.get(field, ""))
            if not low <= value <= high:
                errors.append(f"{label} must be between {low} and {high} (got {value}).")
        except ValueError:
            errors.append(f"{label} must be a number.")

    if s.get("frequency_option", "").upper() not in ("A", "B"):
        errors.append("Frequency option must be A or B.")
    for field in YES_NO_FIELDS:
        if s.get(field, "").lower() not in ("yes", "no"):
            errors.append(f"{field.replace('_', ' ').capitalize()} must be yes or no.")

    try:
        if not parse_work_days(s.get("work_days", "")):
            errors.append("Work days is empty. Use e.g. Mon-Fri or Mon,Tue,Sat.")
    except (ValueError, IndexError):
        errors.append(f"Work days '{s.get('work_days', '')}' is not understood. Use e.g. Mon-Fri or Mon,Tue,Sat.")

    start, end = s.get("work_start", ""), s.get("work_end", "")
    ok_start, ok_end = _is_hhmm(start), _is_hhmm(end)
    if not ok_start:
        errors.append(f"Work start '{start}' must be a time written HH:MM (e.g. 07:00).")
    if not ok_end:
        errors.append(f"Work end '{end}' must be a time written HH:MM (e.g. 17:00).")
    if ok_start and ok_end and start >= end:
        errors.append(f"Work start ({start}) must be earlier than work end ({end}).")

    last = s.get("last_inspection", "")
    if last:
        try:
            datetime.fromisoformat(last)
        except ValueError:
            errors.append(f"Last inspection '{last}' must be blank or written YYYY-MM-DD HH:MM.")

    controls = clean_controls(controls)
    if not controls:
        errors.append("Add at least one control measure.")
    errors.extend(control_id_problems(controls))
    for i, c in enumerate(controls, start=1):
        label = c["control_id"] or f"row {i}"
        if not c["name"]:
            errors.append(f"Control {label}: name is required.")
        if not inspect_items(c["inspect"]):
            errors.append(f"Control {label}: list at least one inspect item (comma-separated).")
    return errors


# ---------- Saving ----------
def backup(path, backup_dir=BACKUP_DIR, now=None):
    """Copy a file to backup_dir/<stem>_<YYYYMMDD_HHMMSS><suffix>. Returns the copy's path, or None."""
    if not path.exists():
        return None
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{path.stem}_{stamp}{path.suffix}"
    shutil.copy2(path, target)
    return target


def site_row(site, controls, columns):
    """sites.csv row: every column in order, control_ids joined with ';'."""
    row = {c: str(site.get(c, "") if site.get(c) is not None else "").strip() for c in columns}
    row["control_ids"] = ";".join(c["control_id"] for c in clean_controls(controls))
    row["frequency_option"] = row.get("frequency_option", "").upper()
    for field in YES_NO_FIELDS:
        if field in row:
            row[field] = row[field].lower()
    return row


def save_site(site, controls, swppp_text, is_new, sites_file=SITES_FILE, swppp_dir=SWPPP_DIR,
              backup_dir=BACKUP_DIR, now=None):
    """Validate, back up, then write the sites.csv row and the SWPPP. Returns (errors, backups).

    Nothing is written if there is any error.
    """
    errors = validate(site, controls, is_new, sites_file)
    if not swppp_text.strip():
        errors.append("The SWPPP text is empty.")
    if errors:
        return errors, []

    columns, rows = read_sites(sites_file)
    columns = columns + [c for c in SITE_COLUMNS if c not in columns]
    row = site_row(site, controls, columns)
    sid = row["site_id"]
    swppp_path = swppp_dir / f"{sid}.md"

    now = now or datetime.now()
    backups = [p for p in (backup(sites_file, backup_dir, now), backup(swppp_path, backup_dir, now)) if p]

    if is_new:
        rows.append(row)
    else:
        rows = [row if r.get("site_id", "").lower() == sid.lower() else r for r in rows]
    sites_file.parent.mkdir(parents=True, exist_ok=True)
    with sites_file.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({c: r.get(c, "") for c in columns})

    swppp_dir.mkdir(parents=True, exist_ok=True)
    swppp_path.write_text(swppp_text.replace("\r\n", "\n"), encoding="utf-8")
    return [], backups
