"""All writing to the inspector's records: validate, back up, save. Plain Python, no AI.

Add Site tab:      appends a row to the "sites" sheet and writes data/swppps/<site_id>.md (new sites only).
Site Records tab:  saves edits to ONE sheet of data/INSPECTOR_RECORDS.xlsx ("sites" rows edited in place;
                   "inspections" / "deficiencies" rows edited or added, never deleted), stamping
                   updated_by / updated_at on each changed or added row.
Other sheets, column order, cell formats, and extra columns are kept. Before any write, the workbook (and an
old SWPPP) is copied to data/backups/<name>_<YYYYMMDD_HHMMSS>.<ext>. If Excel has the workbook open,
nothing is written. Every function takes its file paths as parameters so tests can use a temp folder.
"""
import os
import re
import shutil
from copy import copy
from datetime import datetime
from datetime import time as dt_time

from openpyxl import load_workbook

from agent import swppp, workbook
from agent.scheduler import LOCAL, parse_work_days
from agent.timeparse import clock_text, datetime_text, parse_clock, parse_local_datetime
from config import (DATA, DEFAULT_WORK_DAYS, DEFAULT_WORK_END, DEFAULT_WORK_START, INSPECTOR_RECORDS,
                    STORM_THRESHOLD_IN)

SWPPP_DIR = swppp.SWPPP_DIR
BACKUP_DIR = DATA / "backups"
LOCKED_MESSAGE = "INSPECTOR_RECORDS.xlsx is open in Excel. Close it and click Save again."

SITE_COLUMNS = workbook.SHEETS["sites"]
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


# ---------- Reading ----------
def read_sites(records_file=INSPECTOR_RECORDS):
    """(columns, rows) from the workbook's sites sheet. Rows are dicts of strings, in sheet order.

    Raises workbook.WorkbookError if the workbook, sheet, or a required column is missing.
    """
    columns, rows = workbook.read_sheet_rows("sites", records_file)
    return columns, [r for _, r in rows]


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
def _clock(value):
    """Parsed time, or None if unreadable."""
    try:
        return parse_clock(value)
    except ValueError:
        return None


def _text(value):
    return str(value if value is not None else "").strip()


def now_local():
    """Current site-local time without a time zone (how the workbook stores times)."""
    return datetime.now(LOCAL).replace(tzinfo=None)


def site_field_errors(site):
    """Errors in a site's own fields (everything except site_id and the control measures)."""
    errors = []
    s = {k: _text(v) for k, v in site.items()}
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
    t_start, t_end = _clock(start), _clock(end)
    if t_start is None:
        errors.append(f"Work start '{start}' must be a time written HH:MM (e.g. 07:00).")
    if t_end is None:
        errors.append(f"Work end '{end}' must be a time written HH:MM (e.g. 17:00).")
    if t_start is not None and t_end is not None and t_start >= t_end:
        errors.append(f"Work start ({start}) must be earlier than work end ({end}).")

    last = s.get("last_inspection", "")
    if last:
        try:
            parse_local_datetime(last)
        except ValueError:
            errors.append(f"Last inspection '{last}' must be blank or a time written YYYY-MM-DD HH:MM "
                          "(or M/D/YYYY H:MM).")
    return errors


def validate(site, controls, records_file=INSPECTOR_RECORDS):
    """Add Site: plain-English errors; an empty list means the new site can be saved."""
    errors = []
    sid = _text(site.get("site_id"))
    _, rows = read_sites(records_file)
    existing = {r.get("site_id", "").lower() for r in rows}

    if not sid:
        errors.append("Site ID is required.")
    elif not SITE_ID_RE.match(sid):
        errors.append(f"Site ID '{sid}' may only contain letters, digits, and hyphens.")
    elif sid.lower() in existing:
        errors.append(f"Site ID '{sid}' already exists. Edit it on the Site Records tab instead.")
    errors.extend(site_field_errors(site))

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


def control_ids_of(site):
    return [c.strip() for c in _text(site.get("control_ids")).split(";") if c.strip()]


def validate_site_row(site):
    """Site Records, sites sheet: same field rules as Add Site, plus the control_ids text."""
    errors = list(site_field_errors(site))
    ids = control_ids_of(site)
    if not ids:
        errors.append("control_ids needs at least one control ID (e.g. SF-1;IP-2).")
    errors.extend(control_id_problems([{"control_id": c} for c in ids]))
    return errors


def _time_errors(row, field, label, now, required=True):
    """(parsed time or None, errors) for a log time: required, readable, not in the future."""
    text = _text(row.get(field))
    if not text:
        return None, ([f"{label} is required."] if required else [])
    try:
        when = parse_local_datetime(text)
    except ValueError:
        return None, [f"{label} '{text}' is not a date and time (use YYYY-MM-DD HH:MM)."]
    if when > now:
        return when, [f"{label} {datetime_text(when)} is in the future."]
    return when, []


def validate_inspection_row(row, sites_by_id, now=None):
    now = now or now_local()
    errors = []
    if _text(row.get("site_id")) not in sites_by_id:
        errors.append(f"Site ID '{_text(row.get('site_id'))}' is not in the sites sheet.")
    errors += _time_errors(row, "inspected_at", "Inspected at", now)[1]
    if _text(row.get("type")) not in CHOICES["type"]:
        errors.append("Type must be routine or storm.")
    if not _text(row.get("inspector")):
        errors.append("Inspector is required.")
    return errors


def validate_deficiency_row(row, sites_by_id, now=None):
    now = now or now_local()
    errors = []
    sid, cid = _text(row.get("site_id")), _text(row.get("control_id"))
    if sid not in sites_by_id:
        errors.append(f"Site ID '{sid}' is not in the sites sheet.")
    elif cid not in control_ids_of(sites_by_id[sid]):
        errors.append(f"Control '{cid}' is not one of site {sid}'s controls "
                      f"({', '.join(control_ids_of(sites_by_id[sid])) or 'none listed'}).")
    found, found_errors = _time_errors(row, "found_at", "Found at", now)
    errors += found_errors
    if not _text(row.get("description")):
        errors.append("Description is required.")
    if _text(row.get("category")) not in CHOICES["category"]:
        errors.append("Category must be routine_maintenance, corrective_no_new_control, or corrective_new_control.")
    status = _text(row.get("status"))
    if status == "closed":
        if not _text(row.get("closed_at")):
            errors.append("A closed deficiency needs closed_at (when the fix was finished).")
        else:
            closed, closed_errors = _time_errors(row, "closed_at", "Closed at", now)
            errors += closed_errors
            if found and closed and closed < found:
                errors.append(f"Closed at ({datetime_text(closed)}) can't be before found at "
                              f"({datetime_text(found)}).")
    elif status == "open":
        if _text(row.get("closed_at")):
            errors.append("An open deficiency must have a blank closed_at. Set status to closed, or clear closed_at.")
    else:
        errors.append("Status must be open or closed.")
    return errors


# ---------- Site Records: editing a whole sheet ----------
SHEET_ID = {"sites": "site_id", "inspections": "inspection_id", "deficiencies": "deficiency_id"}
ID_PREFIX = {"inspections": "I-", "deficiencies": "D-"}
AUDIT_COLUMNS = ["updated_by", "updated_at"]
ROW_KEY = "_row"                    # Excel row number of an existing row; None for a row added in the editor
CHOICES = {
    "frequency_option": ["A", "B"],
    **{f: ["yes", "no"] for f in YES_NO_FIELDS},
    "type": ["routine", "storm"],
    "category": ["routine_maintenance", "corrective_no_new_control", "corrective_new_control"],
    "status": ["open", "closed"],
}
NO_CHANGES = "No changes to save."


def editor_text(column, value):
    """A st.data_editor cell (Timestamp, time, float, None/NaN/NaT, text) -> the workbook's text form."""
    if value is None or (isinstance(value, float) and value != value) or str(value) == "NaT":
        return ""
    if column in workbook.CLOCK_COLUMNS and isinstance(value, (datetime, dt_time)):
        return clock_text(value)
    if isinstance(value, datetime):
        return datetime_text(value)
    if isinstance(value, dt_time):
        return clock_text(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return " ".join(str(value).split())


def _row_number(value):
    """Editor value of ROW_KEY -> int, or None for a new row (None/NaN/blank)."""
    if value is None or value == "" or (isinstance(value, float) and value != value):
        return None
    return int(value)


def next_id(prefix, ids):
    """Next free ID like I-009 after the highest I-### in ids."""
    numbers = [m.group(1) for i in ids if (m := re.fullmatch(re.escape(prefix) + r"(\d+)", _text(i)))]
    width = max([3] + [len(n) for n in numbers])
    return f"{prefix}{max([0] + [int(n) for n in numbers]) + 1:0{width}d}"


def plan_sheet_edits(sheet, original, edited, sites_rows, now=None):
    """Compare an edited sheet with what was loaded. Returns (plan, errors).

    original, edited: row dicts of strings; existing rows carry ROW_KEY (their Excel row number),
    rows added in the editor have no ROW_KEY. plan = {"sheet", "added": [rows], "changed": [{"row",
    "id", "cells": {column: (old, new)}, "new": row}]}. New rows get the next I-### / D-### if left blank.
    """
    id_col = SHEET_ID[sheet]
    label = {"sites": "Site", "inspections": "Inspection", "deficiencies": "Deficiency"}[sheet]
    by_row = {_row_number(r[ROW_KEY]): r for r in original}
    columns = [c for c in (original[0] if original else {}) if c != ROW_KEY] or list(workbook.SHEETS[sheet])
    errors, added, changed = [], [], []

    kept = set()
    for r in edited:
        n = _row_number(r.get(ROW_KEY))
        clean = {c: _text(r.get(c)) for c in r if c != ROW_KEY}
        if n is None:
            if any(v for c, v in clean.items() if c not in AUDIT_COLUMNS):
                added.append({c: clean.get(c, "") for c in columns})
            continue
        kept.add(n)
        old = by_row.get(n)
        if old is None:
            continue
        cells = {c: (_text(old.get(c)), clean.get(c, "")) for c in columns
                 if c not in AUDIT_COLUMNS and _text(old.get(c)) != clean.get(c, "")}
        if id_col in cells:
            errors.append(f"{label} {_text(old.get(id_col))}: {id_col} can't be changed.")
        if cells:
            new = {c: _text(old.get(c)) for c in columns}
            new.update({c: v for c, (_, v) in cells.items()})
            changed.append({"row": n, "id": _text(old.get(id_col)), "cells": cells, "new": new})

    removed = [_text(by_row[n].get(id_col)) or f"row {n}" for n in by_row if n not in kept]
    if removed:
        if sheet == "sites":
            errors.append(f"Sites can't be removed ({', '.join(removed)}). Set active to no instead.")
        else:
            errors.append(f"Deleting rows is not allowed ({', '.join(removed)}). Records are kept; "
                          "correct the values instead.")
    if added and sheet == "sites":
        errors.append("Add new sites on the Add Site tab.")
        added = []

    if sheet in ID_PREFIX:                                    # fill blank IDs, refuse duplicates
        taken = [_text(r.get(id_col)) for r in original]
        for row in added:
            if not row[id_col]:
                row[id_col] = next_id(ID_PREFIX[sheet], taken)
            elif row[id_col] in taken:
                errors.append(f"{label} ID {row[id_col]} is already used. Leave it blank to get the next free ID.")
            taken.append(row[id_col])

    sites_by_id = {_text(s.get("site_id")): s for s in sites_rows}
    for row, name in [(c["new"], c["id"]) for c in changed] + [(a, a.get(id_col) or "(new)") for a in added]:
        if sheet == "sites":
            problems = validate_site_row(row)
        elif sheet == "inspections":
            problems = validate_inspection_row(row, sites_by_id, now)
        else:
            problems = validate_deficiency_row(row, sites_by_id, now)
        errors += [f"{label} {name}: {p}" for p in problems]

    plan = {"sheet": sheet, "added": added, "changed": changed}
    if not errors and not added and not changed:
        errors.append(NO_CHANGES)
    return plan, errors


def describe_plan(plan):
    """Preview lines: added rows and changed cells (old -> new)."""
    id_col = SHEET_ID[plan["sheet"]]
    lines = []
    for row in plan["added"]:
        filled = ", ".join(f"{c} = {v}" for c, v in row.items() if v and c != id_col and c not in AUDIT_COLUMNS)
        lines.append(f"Add {row[id_col]}: {filled}")
    for ch in plan["changed"]:
        cells = "; ".join(f"{c}: '{old}' -> '{new}'" for c, (old, new) in ch["cells"].items())
        lines.append(f"Change {ch['id']} (Excel row {ch['row']}): {cells}")
    return lines


class StaleWorkbookError(ValueError):
    """The workbook changed (e.g. in Excel) after the page loaded it."""


def save_sheet_edits(sheet, original, edited, saved_by, records_file=INSPECTOR_RECORDS, backup_dir=BACKUP_DIR,
                     now=None):
    """Site Records: validate, back up, then write ONLY this sheet's added/changed rows.

    Returns (errors, backups, plan). Nothing is written if there is any error. Changed and added rows get
    updated_by / updated_at (columns are appended to the sheet if missing).
    """
    now = now or now_local()
    try:
        _, sites_rows = read_sites(records_file)
    except workbook.WorkbookError as e:
        return [str(e)], [], None
    plan, errors = plan_sheet_edits(sheet, original, edited, sites_rows, now)
    if not _text(saved_by) and errors != [NO_CHANGES]:
        errors.insert(0, "Enter your name in Saved by.")
    if errors:
        return errors, [], plan
    if is_locked(records_file):
        return [LOCKED_MESSAGE], [], plan

    backups = [p for p in [backup(records_file, backup_dir, now)] if p]
    try:
        write_sheet_edits(records_file, plan, _text(saved_by), now)
    except (PermissionError, StaleWorkbookError) as e:
        for p in backups:
            p.unlink(missing_ok=True)
        return [LOCKED_MESSAGE if isinstance(e, PermissionError) else str(e)], [], plan
    return [], backups, plan


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
    """Row for the sites sheet: every column in order, control_ids joined with ';'."""
    row = {c: str(site.get(c, "") if site.get(c) is not None else "").strip() for c in columns}
    row["control_ids"] = ";".join(c["control_id"] for c in clean_controls(controls))
    row["frequency_option"] = row.get("frequency_option", "").upper()
    for field in YES_NO_FIELDS:
        if field in row:
            row[field] = row[field].lower()
    # Write times the standard way, even if typed (or pasted from Excel) as 7:00 or 11/9/2026 9:00.
    for field, parse, fmt in (("work_start", parse_clock, clock_text), ("work_end", parse_clock, clock_text),
                              ("last_inspection", parse_local_datetime, datetime_text)):
        if row.get(field):
            try:
                row[field] = fmt(parse(row[field]))
            except ValueError:
                pass            # validate() reports it; the preview shows it as typed
    return row


def save_site(site, controls, swppp_text, records_file=INSPECTOR_RECORDS, swppp_dir=SWPPP_DIR,
              backup_dir=BACKUP_DIR, now=None):
    """Add Site: validate, back up, then append the site row (sites sheet) and write the SWPPP.

    Returns (errors, backups). Nothing is written if there is any error, including the workbook being
    open in Excel. Existing sites are edited on the Site Records tab, not here.
    """
    try:
        errors = validate(site, controls, records_file)
        columns, _ = read_sites(records_file)
    except workbook.WorkbookError as e:
        return [str(e)], []
    if not swppp_text.strip():
        errors.append("The SWPPP text is empty.")
    if errors:
        return errors, []
    if is_locked(records_file):
        return [LOCKED_MESSAGE], []

    columns = columns + [c for c in SITE_COLUMNS if c not in columns]
    row = site_row(site, controls, columns)
    swppp_path = swppp_dir / f"{row['site_id']}.md"

    now = now or datetime.now()
    backups = [p for p in (backup(records_file, backup_dir, now), backup(swppp_path, backup_dir, now)) if p]
    try:
        write_site_row(records_file, row)
    except PermissionError:                 # Excel grabbed the file between the check and the save
        for p in backups:
            p.unlink(missing_ok=True)
        return [LOCKED_MESSAGE], []

    swppp_dir.mkdir(parents=True, exist_ok=True)
    swppp_path.write_text(swppp_text.replace("\r\n", "\n"), encoding="utf-8")
    return [], backups


def is_locked(path):
    """True if another program (Excel) holds the file so it can't be written."""
    try:
        with open(path, "r+b"):
            return False
    except PermissionError:
        return True


def _columns(ws, wanted):
    """{column name: column number} for row 1, appending any wanted column the sheet lacks (bold header)."""
    header = [" ".join(str(c.value).split()) if c.value is not None else "" for c in ws[1]]
    while header and not header[-1]:
        header.pop()
    for name in wanted:
        if name not in header:
            header.append(name)
            cell = ws.cell(1, len(header), name)
            cell.font = copy(ws.cell(1, 1).font)
    return {name: i for i, name in enumerate(header, start=1) if name}


def _last_row(ws, index):
    """Last row with any value in a named column (1 if only the header)."""
    last = 1
    for r in range(2, ws.max_row + 1):
        if any(ws.cell(r, i).value not in (None, "") for i in index.values()):
            last = r
    return last


def _put(ws, r, index, column, text):
    value, fmt = workbook.cell_value(column, text)
    cell = ws.cell(r, index[column])
    cell.value = value
    if fmt:
        cell.number_format = fmt


def _save(wb, records_file):
    """Save to a temp file next to the workbook, then swap it in. Raises PermissionError if locked."""
    tmp = records_file.with_name(records_file.stem + ".saving.xlsx")
    try:
        wb.save(tmp)
        os.replace(tmp, records_file)
    finally:
        tmp.unlink(missing_ok=True)
        workbook.clear_cache()


def write_site_row(records_file, row):
    """Append one new site row to the "sites" sheet, keeping the other sheets, formats, and extra columns."""
    wb = load_workbook(records_file)        # full mode: keeps formats and the other two sheets
    ws = wb["sites"]
    index = _columns(ws, list(row))
    target = _last_row(ws, index) + 1
    for name in index:
        if name in row:
            _put(ws, target, index, name, row[name])
    _save(wb, records_file)


def write_sheet_edits(records_file, plan, saved_by, now):
    """Write a plan from plan_sheet_edits into its sheet only: changed cells in place, added rows at the end."""
    wb = load_workbook(records_file)
    sheet = plan["sheet"]
    ws = wb[sheet]
    id_col = SHEET_ID[sheet]
    wanted = [c for row in [ch["new"] for ch in plan["changed"]] + plan["added"] for c in row] + AUDIT_COLUMNS
    index = _columns(ws, list(dict.fromkeys(wanted)))
    stamp = datetime_text(now)

    for ch in plan["changed"]:
        current = workbook.cell_text(id_col, ws.cell(ch["row"], index[id_col]).value)
        if current != ch["id"]:
            raise StaleWorkbookError(f"INSPECTOR_RECORDS.xlsx changed since this page loaded (Excel row {ch['row']} "
                                     f"is now '{current}', not '{ch['id']}'). Nothing was saved. Press F5 and "
                                     "make the change again.")
        for column, (_, new) in ch["cells"].items():
            _put(ws, ch["row"], index, column, new)
        _put(ws, ch["row"], index, "updated_by", saved_by)
        _put(ws, ch["row"], index, "updated_at", stamp)

    r = _last_row(ws, index)
    for row in plan["added"]:
        r += 1
        for column, text in row.items():
            if column in index and column not in AUDIT_COLUMNS:
                _put(ws, r, index, column, text)
        _put(ws, r, index, "updated_by", saved_by)
        _put(ws, r, index, "updated_at", stamp)
    _save(wb, records_file)
