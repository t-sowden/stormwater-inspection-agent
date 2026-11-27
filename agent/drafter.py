"""Draft report wording with the local AI (Ollama). The AI writes ONLY the narrative.

Every date, deadline, rainfall figure, and flag is computed in Python and added as tables by
assemble_report() / assemble_report_docx(). validator.check() rejects any narrative that contains dates or forbidden claims;
the app then falls back to template_narrative(), which is plain Python.
"""
import json
from io import BytesIO

import requests
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from agent.messages import AI_ROLE, AI_ROLE_SHORT
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


# ---------- Report layout (shared by the markdown and Word versions) ----------
TITLE = "DRAFT Construction Stormwater Inspection Report"
BANNER = f"DRAFT: inspector review required. {AI_ROLE_SHORT}"
RAIN_HEADING = "Rainfall (NOAA ASOS via Aviation Weather Center)"
RAIN_COLUMNS = ["Station", "Distance (mi)", "Max 24-h rain (in)", "0.25 in reached", "Site gauge (in)"]
FINDINGS_HEADING = "Findings and deadlines (computed by Python)"
FINDINGS_COLUMNS = ["Control", "Citation", "Condition", "Category", "Action", "Deadline", "Rule", "Flags"]
OPEN_HEADING = "Open items from earlier inspections"
OPEN_COLUMNS = ["ID", "Control", "Description", "Action", "Deadline", "Rule", "Flags"]
FLAGS_HEADING = "Flags for the inspector"
REVIEW_HEADING = "Inspector review"
REVIEW_FIELDS = [("Reviewed and edited by", "______________________"),
                 ("Signature", "______________________"), ("Date", "__________")]
WORD_PAGE_HEADER = "DRAFT - inspector review required"


def summary_lines(facts):
    """(label, value) pairs shown under the banner."""
    return [("Site", f"{facts['site_name']} ({facts['site_id']})"),
            ("Inspector", facts["inspector"] or "(not entered)"),
            ("Inspection", f"{facts['inspection_type']}, {facts['inspection_time']}"),
            ("Report due (CGP 4.7.1, R9)", facts["report_due"])]


def rain_row(facts):
    rain = facts["rainfall"]
    gauge = facts["gauge_reading"] if facts["gauge_reading"] is not None else "not read"
    return [rain["station"], rain["distance_mi"], f"{rain['max_24h_in']:.2f}", rain["trigger"], gauge]


def finding_rows(facts):
    rows = []
    for f in facts["findings"]:
        if not f["deadlines"]:
            rows.append([f["title"], f["citation"], f["condition"], "-", "-", "-", "-", ""])
        for label, when, rule in f["deadlines"]:
            rows.append([f["title"], f["citation"], f["condition"], f["category_label"], label, when, rule,
                         ", ".join(f["flags"])])
    return rows


def open_item_rows(facts):
    rows = []
    for o in facts["open_items"]:
        label, when, rule = o["deadlines"][0]
        rows.append([o["deficiency_id"], o["control_id"], o["description"], label, when, rule, ", ".join(o["flags"])])
    return rows


def flags_text(facts):
    return ", ".join(facts["flags"]) if facts["flags"] else "None."


# ---------- Markdown ----------
def _md_table(columns, rows):
    return (["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
            + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def assemble_report(facts, narrative, source):
    """Full report in markdown: narrative + Python-computed tables + blank signature block."""
    out = [f"# {TITLE}", f"**{BANNER}**", ""]
    out += [f"- **{label}:** {value}" for label, value in summary_lines(facts)]
    out += ["", f"## Narrative ({source})", narrative, "", f"## {RAIN_HEADING}"]
    out += _md_table(RAIN_COLUMNS, [rain_row(facts)])
    out += ["", f"## {FINDINGS_HEADING}"]
    out += _md_table(FINDINGS_COLUMNS, finding_rows(facts))
    if facts["open_items"]:
        out += ["", f"## {OPEN_HEADING}"]
        out += _md_table(OPEN_COLUMNS, open_item_rows(facts))
    out += ["", f"## {FLAGS_HEADING}", flags_text(facts),
            "", f"## {REVIEW_HEADING}",
            "   ".join(f"{label}: {blank}" for label, blank in REVIEW_FIELDS),
            "", f"_{AI_ROLE}_"]
    return "\n".join(out)


# ---------- Word (.docx) ----------
def _field(paragraph, code):
    """Insert a Word field such as PAGE or NUMPAGES (updates when the document is opened or printed)."""
    run = paragraph.add_run()
    for tag, attrs in (("w:fldChar", {"w:fldCharType": "begin"}), ("w:instrText", None),
                       ("w:fldChar", {"w:fldCharType": "end"})):
        el = OxmlElement(tag)
        if attrs:
            for k, v in attrs.items():
                el.set(qn(k), v)
        else:
            el.set(qn("xml:space"), "preserve")
            el.text = f" {code} "
        run._r.append(el)


def _docx_table(doc, columns, rows):
    """Table Grid table with a bold, shaded header row that repeats on each page."""
    table = doc.add_table(rows=1, cols=len(columns))
    table.style = "Table Grid"
    header = table.rows[0]
    tr_pr = header._tr.get_or_add_trPr()
    repeat = OxmlElement("w:tblHeader")
    repeat.set(qn("w:val"), "true")
    tr_pr.append(repeat)
    for cell, text in zip(header.cells, columns):
        run = cell.paragraphs[0].add_run(text)
        run.bold = True
        shading = OxmlElement("w:shd")
        shading.set(qn("w:val"), "clear")
        shading.set(qn("w:color"), "auto")
        shading.set(qn("w:fill"), "D9D9D9")
        cell._tc.get_or_add_tcPr().append(shading)
    for row in rows:
        cells = table.add_row().cells
        for cell, value in zip(cells, row):
            cell.text = str(value)
    for row in table.rows:                       # 8-column tables: a slightly smaller font so they fit
        for cell in row.cells:
            for p in cell.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(9 if len(columns) > 5 else 10)
    return table


def assemble_report_docx(facts, narrative, source):
    """The same report as assemble_report(), as a Word document (bytes). Built from facts, not the markdown."""
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)          # US Letter
    section.left_margin = section.right_margin = Inches(1)
    section.top_margin = section.bottom_margin = Inches(1)

    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = "Calibri", Pt(11)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    for name in ("Title", "Heading 1"):
        doc.styles[name].font.name = "Calibri"

    section.header.paragraphs[0].text = WORD_PAGE_HEADER
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run("Page ")
    _field(footer, "PAGE")
    footer.add_run(" of ")
    _field(footer, "NUMPAGES")

    doc.add_heading(TITLE, level=0)
    banner = doc.add_paragraph().add_run(BANNER)
    banner.bold = True
    banner.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
    for label, value in summary_lines(facts):
        p = doc.add_paragraph(style="List Bullet")
        p.add_run(f"{label}: ").bold = True
        p.add_run(str(value))

    doc.add_heading(f"Narrative ({source})", level=1)
    for part in [p.strip() for p in narrative.split("\n\n") if p.strip()]:
        doc.add_paragraph(part)

    doc.add_heading(RAIN_HEADING, level=1)
    _docx_table(doc, RAIN_COLUMNS, [rain_row(facts)])
    doc.add_heading(FINDINGS_HEADING, level=1)
    _docx_table(doc, FINDINGS_COLUMNS, finding_rows(facts))
    if facts["open_items"]:
        doc.add_heading(OPEN_HEADING, level=1)
        _docx_table(doc, OPEN_COLUMNS, open_item_rows(facts))

    doc.add_heading(FLAGS_HEADING, level=1)
    doc.add_paragraph(flags_text(facts))
    doc.add_heading(REVIEW_HEADING, level=1)
    for label, blank in REVIEW_FIELDS:
        doc.add_paragraph(f"{label}: {blank}")
    doc.add_paragraph().add_run(AI_ROLE).italic = True

    out = BytesIO()
    doc.save(out)
    return out.getvalue()
