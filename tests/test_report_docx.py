"""Word (.docx) draft report: same content as the markdown report, built from the facts (no AI, no new dates)."""
from io import BytesIO

from docx import Document

from agent import drafter
from agent.messages import AI_ROLE, AI_ROLE_SHORT
from report_sample import NARRATIVE, sample_facts

SOURCE = "AI-drafted, validated"


def build(facts=None, narrative=NARRATIVE):
    data = drafter.assemble_report_docx(facts or sample_facts(), narrative, SOURCE)
    return data, Document(BytesIO(data))


def table_cells(doc):
    return [cell.text for t in doc.tables for row in t.rows for cell in row.cells]


def texts(doc):
    return [p.text for p in doc.paragraphs]


def test_output_is_nonempty_docx_bytes():
    data, _ = build()
    assert isinstance(data, bytes) and len(data) > 1000 and data[:2] == b"PK"      # a .docx is a zip


def test_draft_banner_bold_red_and_same_as_markdown():
    _, doc = build()
    banner = next(p for p in doc.paragraphs if p.text.startswith("DRAFT: inspector review required."))
    assert banner.text == f"DRAFT: inspector review required. {AI_ROLE_SHORT}"
    run = banner.runs[0]
    assert run.bold and str(run.font.color.rgb) == "C00000"
    assert f"**{banner.text}**" in drafter.assemble_report(sample_facts(), NARRATIVE, SOURCE)
    assert doc.paragraphs[0].text == "DRAFT Construction Stormwater Inspection Report"
    assert doc.paragraphs[0].style.name == "Title"


def test_every_deadline_and_finding_is_in_a_table():
    facts = sample_facts()
    _, doc = build(facts)
    cells = table_cells(doc)
    deadlines = [when for f in facts["findings"] for _, when, _ in f["deadlines"]] + \
                [when for o in facts["open_items"] for _, when, _ in o["deadlines"]]
    assert deadlines and all(when in cells for when in deadlines)
    assert all(f["title"] in cells for f in facts["findings"])
    assert all(o["deficiency_id"] in cells and o["description"] in cells for o in facts["open_items"])
    assert facts["rainfall"]["station"] in cells and "0.41" in cells and "0.38" in cells


def test_narrative_present_and_current_text_used():
    _, doc = build()
    for part in NARRATIVE.split("\n\n"):
        assert part in texts(doc)
    assert f"Narrative ({SOURCE})" in texts(doc)
    _, revised = build(narrative="Revised after the revise chat: plainer wording.")
    assert "Revised after the revise chat: plainer wording." in texts(revised)
    assert NARRATIVE.split("\n\n")[0] not in texts(revised)


def test_signature_lines_blank_and_closing_note():
    _, doc = build()
    t = texts(doc)
    review = t.index("Inspector review")
    assert t[review + 1:review + 4] == ["Reviewed and edited by: ______________________",
                                        "Signature: ______________________", "Date: __________"]
    assert t[-1] == AI_ROLE
    assert f"_{AI_ROLE}_" in drafter.assemble_report(sample_facts(), NARRATIVE, SOURCE)


def test_sections_in_markdown_order_and_open_items_optional():
    _, doc = build()
    headings = [p.text for p in doc.paragraphs if p.style.name == "Heading 1"]
    assert headings == [f"Narrative ({SOURCE})", drafter.RAIN_HEADING, drafter.FINDINGS_HEADING,
                        drafter.OPEN_HEADING, drafter.FLAGS_HEADING, drafter.REVIEW_HEADING]
    facts = sample_facts()
    facts.update(open_items=[], flags=[], gauge_reading=None, inspector="")
    _, doc = build(facts)
    assert drafter.OPEN_HEADING not in texts(doc) and len(doc.tables) == 2
    assert "None." in texts(doc) and "not read" in table_cells(doc)
    assert any(p.text == "Inspector: (not entered)" for p in doc.paragraphs)


def test_page_setup_tables_header_and_footer():
    _, doc = build()
    s = doc.sections[0]
    assert (s.page_width.inches, s.page_height.inches) == (8.5, 11.0)
    assert {s.left_margin.inches, s.right_margin.inches, s.top_margin.inches, s.bottom_margin.inches} == {1.0}
    assert doc.styles["Normal"].font.name == "Calibri" and doc.styles["Normal"].font.size.pt == 11
    assert s.header.paragraphs[0].text == "DRAFT - inspector review required"
    footer_xml = s.footer._element.xml
    assert " PAGE " in footer_xml and " NUMPAGES " in footer_xml
    for table in doc.tables:
        assert table.style.name == "Table Grid"
        header = table.rows[0]
        assert all(run.bold for cell in header.cells for run in cell.paragraphs[0].runs)
        assert "D9D9D9" in header._tr.xml and "tblHeader" in header._tr.xml
