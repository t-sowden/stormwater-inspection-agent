"""Draft report wording with the local AI (Ollama). The AI writes ONLY the narrative.

Every date, deadline, rainfall figure, and flag is computed in Python and added as tables by
assemble_report(). validator.check() rejects any narrative that contains dates or forbidden claims;
the app then falls back to template_narrative(), which is plain Python.
"""
import json

import requests

from config import OLLAMA_HOST, OLLAMA_MODEL

SYSTEM = (
    "You write the narrative section of a DRAFT construction stormwater inspection report "
    "for an inspector to review. Follow these rules exactly:\n"
    "1. Use only the facts provided. Do not invent observations, measurements, or controls.\n"
    "2. Do NOT write any dates, days of the week, clock times, deadlines, or durations. "
    "The app adds every date and deadline in tables. Refer to 'the deadlines table' instead.\n"
    "3. Do NOT say the inspection is complete, signed, or certified, and do NOT say the site is "
    "compliant or in compliance. The inspector decides that.\n"
    "4. Cite SWPPP sections exactly as given in the facts, for example 'SWPPP §4.1'.\n"
    "5. Write 2 to 4 short paragraphs in plain professional language: site conditions, findings, "
    "and follow-up needed. No headings, no tables, no bullet lists."
)


def _facts_for_ai(facts):
    """The facts the AI may see: no dates, so it has none to copy."""
    return {
        "site": f"{facts['site_name']} ({facts['site_id']})",
        "inspection_type": facts["inspection_type"],
        "weather_and_site_notes": facts.get("weather_notes", ""),
        "rainfall": {"station": facts["rainfall"]["station"],
                     "distance_mi": facts["rainfall"]["distance_mi"],
                     "max_24h_rain_in": facts["rainfall"]["max_24h_in"],
                     "storm_threshold_reached": facts["rainfall"]["trigger"] != "none"},
        "findings": [{"control": f["title"], "citation": f["citation"], "condition": f["condition"],
                      "inspector_notes": f["notes"], "category": f["category_label"]}
                     for f in facts["findings"]],
        "open_items_from_earlier_inspections": [
            {"control": o["control_id"], "description": o["description"]} for o in facts["open_items"]],
        "flags_for_inspector": facts["flags"],
    }


def ollama_narrative(facts, previous=None, instruction=None, timeout=300):
    """Ask the local model for a narrative (or a revision of `previous`). Returns text or raises."""
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": "Facts (JSON):\n" + json.dumps(_facts_for_ai(facts), indent=2)
                 + "\n\nWrite the narrative now."}]
    if previous and instruction:
        messages += [{"role": "assistant", "content": previous},
                     {"role": "user", "content": "Revise the narrative as follows, keeping every rule: "
                      + instruction}]
    r = requests.post(f"{OLLAMA_HOST}/api/chat", timeout=timeout, json={
        "model": OLLAMA_MODEL, "messages": messages, "stream": False,
        "options": {"temperature": 0.2}})
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def template_narrative(facts):
    """Plain-Python narrative used when the AI is unavailable or its draft fails validation."""
    rain = facts["rainfall"]
    parts = [
        f"This draft covers a {facts['inspection_type']} inspection at {facts['site_name']}. "
        f"Rainfall data are from station {rain['station']}, {rain['distance_mi']} mi from the site, "
        f"with a maximum rolling 24-hour total of {rain['max_24h_in']:.2f} in."
        + (f" Site notes: {facts['weather_notes']}" if facts.get("weather_notes") else "")
    ]
    issues = [f for f in facts["findings"] if f["condition"] != "OK"]
    if issues:
        lines = [f"{f['title']} ({f['citation']}): {f['category_label'].lower()}"
                 + (f", {f['notes']}" if f["notes"] else "") for f in issues]
        parts.append("Findings: " + "; ".join(lines) + ".")
    else:
        parts.append("No deficiencies were recorded for the controls listed in the SWPPP.")
    if facts["open_items"]:
        parts.append("Open items from earlier inspections remain listed below for follow-up.")
    parts.append("Required actions and their deadlines are listed in the deadlines table. "
                 "The inspector reviews this draft before it is finalized.")
    return "\n\n".join(parts)


def assemble_report(facts, narrative, source):
    """Full report in markdown: narrative + Python-computed tables + blank signature block."""
    rain = facts["rainfall"]
    out = [
        "# DRAFT Construction Stormwater Inspection Report",
        "**DRAFT: inspector review required. The agent does not complete, sign, or file this report.**",
        "",
        f"- **Site:** {facts['site_name']} ({facts['site_id']})",
        f"- **Inspector:** {facts['inspector'] or '(not entered)'}",
        f"- **Inspection:** {facts['inspection_type']}, {facts['inspection_time']}",
        f"- **Report due (CGP 4.7.1, R9):** {facts['report_due']}",
        "",
        f"## Narrative ({source})",
        narrative,
        "",
        "## Rainfall (NOAA ASOS via Aviation Weather Center)",
        "| Station | Distance (mi) | Max 24-h rain (in) | 0.25 in reached | Site gauge (in) |",
        "| --- | --- | --- | --- | --- |",
        f"| {rain['station']} | {rain['distance_mi']} | {rain['max_24h_in']:.2f} | {rain['trigger']} | "
        f"{facts['gauge_reading'] if facts['gauge_reading'] is not None else 'not read'} |",
        "",
        "## Findings and deadlines (computed by Python)",
        "| Control | Citation | Condition | Category | Action | Deadline | Rule | Flags |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for f in facts["findings"]:
        if not f["deadlines"]:
            out.append(f"| {f['title']} | {f['citation']} | {f['condition']} | - | - | - | - | |")
        for label, when, rule in f["deadlines"]:
            out.append(f"| {f['title']} | {f['citation']} | {f['condition']} | {f['category_label']} | "
                       f"{label} | {when} | {rule} | {', '.join(f['flags'])} |")
    if facts["open_items"]:
        out += ["", "## Open items from earlier inspections",
                "| ID | Control | Description | Action | Deadline | Rule | Flags |",
                "| --- | --- | --- | --- | --- | --- | --- |"]
        for o in facts["open_items"]:
            label, when, rule = o["deadlines"][0]
            out.append(f"| {o['deficiency_id']} | {o['control_id']} | {o['description']} | {label} | "
                       f"{when} | {rule} | {', '.join(o['flags'])} |")
    out += ["", "## Flags for the inspector",
            ", ".join(facts["flags"]) if facts["flags"] else "None.",
            "", "## Inspector review",
            "Reviewed and edited by: ______________________   Signature: ______________________   Date: __________",
            "", "_The agent never marks inspections complete, signs reports, or edits inspection records._"]
    return "\n".join(out)
