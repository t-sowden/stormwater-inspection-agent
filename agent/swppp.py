"""Find SWPPP sections for a site and build a cited inspection checklist. Plain Python, no AI.

Each SWPPP is a markdown file: data/swppps/<site_id>.md
Control sections use the heading format:   ## 4.1 Silt Fence SF-1
(number, name, control ID). Bullet lines starting 'Inspect:' become checklist items.
"""
import re

from config import DATA, STORM_THRESHOLD_IN

SWPPP_DIR = DATA / "swppps"
HEADING = re.compile(r"^##\s+(\d+(?:\.\d+)*)\s+(.+?)\s*$")
CONTROL_ID = re.compile(r"\b([A-Z]{2,3}-\d+)$")
INCHES = re.compile(r"(\d*\.\d+|\d+)\s*(?:in\b|inch|inches|\")", re.I)


def load_sections(site_id):
    """All sections of a site's SWPPP: [{number, title, control_id, lines}]. Empty if no file."""
    path = SWPPP_DIR / f"{site_id}.md"
    if not path.exists():
        return []
    sections, current = [], None
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        m = HEADING.match(raw)
        if m:
            number, title = m.group(1), m.group(2)
            cid = CONTROL_ID.search(title)
            current = {"number": number, "title": title,
                       "control_id": cid.group(1) if cid else "", "lines": []}
            sections.append(current)
        elif current is not None and raw.strip().startswith("-"):
            current["lines"].append(raw.strip()[1:].strip())
    return sections


def section_ids(site_id):
    return {s["number"] for s in load_sections(site_id)}


def sections_for(site_id, control_ids, extra_controls=()):
    """Sections for the site's controls (plus any controls with open deficiencies)."""
    wanted = set(control_ids) | set(extra_controls)
    return [s for s in load_sections(site_id) if s["control_id"] in wanted]


def threshold_conflicts(site_id):
    """Warn if the SWPPP states a storm threshold other than the permit's 0.25 in."""
    warnings = []
    for s in load_sections(site_id):
        for line in s["lines"]:
            if re.search(r"storm|rain", line, re.I):
                for value in INCHES.findall(line):
                    if abs(float(value) - STORM_THRESHOLD_IN) > 1e-9:
                        warnings.append(f"SWPPP §{s['number']} states a {value} in storm threshold; "
                                        f"the permit's {STORM_THRESHOLD_IN} in governs and is used.")
    return warnings


def checklist(site_id, control_ids, open_controls=()):
    """Checklist rows: [{citation, control_id, item, note}]."""
    rows = [
        {"citation": "CGP 4.2/4.7", "control_id": "General", "item": "Record rain gauge reading if the site has one", "note": ""},
        {"citation": "CGP 4.2/5.1", "control_id": "General", "item": "Look for any discharge, sheen, or turbid water leaving the site", "note": "Escalate if seen"},
    ]
    for s in sections_for(site_id, control_ids, open_controls):
        note = "Open deficiency, check status" if s["control_id"] in open_controls else ""
        for line in s["lines"]:
            if line.lower().startswith("inspect:"):
                for item in line.split(":", 1)[1].split(","):
                    rows.append({"citation": f"SWPPP §{s['number']}", "control_id": s["control_id"],
                                 "item": f"{s['title']}: {item.strip()}", "note": note})
            elif line.lower().startswith("maintenance trigger:"):
                rows.append({"citation": f"SWPPP §{s['number']}", "control_id": s["control_id"],
                             "item": f"{s['title']}: {line.split(':', 1)[1].strip()}", "note": note})
    return rows
