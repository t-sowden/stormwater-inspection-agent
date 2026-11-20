"""Guardrails for AI text. Plain Python.

check(narrative, allowed_sections) -> (passed, problems)
    The AI narrative must contain NO dates, times, deadlines, or durations (Python adds those),
    must not claim the inspection is complete, signed, certified, or compliant,
    and may only cite SWPPP sections that exist.
check_request(instruction) -> (allowed, reason)
    Revise-chat instructions that try to change dates, mark complete, sign, certify,
    alter records, or override the rules are refused.
"""
import re

MONTHS = r"(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|jun(e)?|jul(y)?|aug(ust)?|sep(t(ember)?)?|oct(ober)?|nov(ember)?|dec(ember)?)"
DAYS = r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
DATE_PATTERNS = [
    (rf"\b{MONTHS}\.?\s+\d{{1,2}}\b", "a calendar date"),
    (rf"\b{DAYS}\b", "a day of the week"),
    (r"\b\d{4}-\d{2}-\d{2}\b", "a calendar date"),
    (r"\b\d{1,2}/\d{1,2}(/\d{2,4})?\b", "a calendar date"),
    (r"\b\d{1,2}:\d{2}\b", "a clock time"),
    (r"\b\d{1,2}\s?(am|pm|a\.m\.|p\.m\.)\b", "a clock time"),
    (r"\bwithin\s+\d+\s*(hours?|days?|business days?)\b", "a deadline duration"),
    (r"\b(deadline|due (by|on|date))\b", "a deadline"),
    (r"\b(tomorrow|tonight|next week|end of (the )?(day|week))\b", "a relative date"),
]
CLAIMS = [
    (r"\binspection (is |was |has been )?(complete|completed|closed)\b", "says the inspection is complete"),
    (r"\bmark(ed)? (as )?complete\b", "marks something complete"),
    (r"\b(signed|signature applied|e-?signed)\b", "claims a signature"),
    (r"\bcertif(y|ies|ied|ication)\b", "certifies"),
    (r"\b(in compliance|is compliant|fully compliant|meets all (permit )?requirements|no violations)\b", "makes a compliance determination"),
]
CITATION = re.compile(r"§\s*(\d+(?:\.\d+)*)|\bsection\s+(\d+(?:\.\d+)+)\b", re.I)


def check(narrative, allowed_sections):
    problems = []
    text = narrative or ""
    if not text.strip():
        return False, ["The draft is empty."]
    for pattern, what in DATE_PATTERNS:
        m = re.search(pattern, text, re.I)
        if m:
            problems.append(f"Contains {what} (\"{m.group(0)}\"). Dates and deadlines come only from Python.")
    for pattern, what in CLAIMS:
        m = re.search(pattern, text, re.I)
        if m:
            problems.append(f"Text {what} (\"{m.group(0)}\"). Only the inspector does that.")
    for m in CITATION.finditer(text):
        num = m.group(1) or m.group(2)
        if num not in allowed_sections:
            problems.append(f"Cites SWPPP section {num}, which does not exist in this site's SWPPP.")
    return (not problems), problems


REFUSE = [
    (r"\b(mark|set|record|log|flag)\b.*\b(complete|completed|done|closed|passed)\b", "mark the inspection complete"),
    (r"\b(sign|signature|e-?sign)\b", "sign the report"),
    (r"\b(certif|attest)", "certify the report"),
    (r"\b(say|state|write|declare|confirm)\b.*\b(compliant|in compliance|no violations|meets)\b", "declare compliance"),
    (r"\b(change|move|extend|push|shift|delay|set|update|edit)\b.*\b(date|deadline|due|time|day)\b", "change a date or deadline"),
    (r"\b(ignore|override|bypass|disable|skip)\b.*\b(rule|rules|instruction|instructions|permit|validator|check|threshold)\b", "override the rules"),
    (r"\b(delete|remove|edit|modify|change|update)\b.*\b(log|record|records|spreadsheet|inspection history|deficienc)", "change inspection records"),
    (r"\b(threshold|trigger)\b.*\b\d*\.\d+\b", "change the storm threshold"),
]


def check_request(instruction):
    text = (instruction or "").lower()
    for pattern, what in REFUSE:
        if re.search(pattern, text):
            return False, (f"I can't {what}. Dates come from the scheduler, records are read-only, "
                           f"and only the inspector reviews, signs, and files the report.")
    return True, ""
