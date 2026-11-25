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
NUM = r"(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|fourteen|twenty-?four)"
UNIT = r"(hours?|days?|business days?|working days?|weeks?)"
DATE_PATTERNS = [
    (rf"\b{MONTHS}\.?\s+\d{{1,2}}\b", "a calendar date"),
    (rf"\b\d{{1,2}}(st|nd|rd|th)?\s+(of\s+)?{MONTHS}\b", "a calendar date"),
    (r"\bthe\s+\d{1,2}(st|nd|rd|th)\b|\b\d{1,2}(st|nd|rd|th)\s+of\b", "a calendar date"),
    (rf"\b{DAYS}\b", "a day of the week"),
    (r"\b\d{4}-\d{2}-\d{2}\b", "a calendar date"),
    (r"\b\d{1,2}/\d{1,2}(/\d{2,4})?\b", "a calendar date"),
    (r"\b\d{1,2}:\d{2}\b", "a clock time"),
    (r"\b\d{1,2}\s?(am|pm|a\.m\.|p\.m\.)\b", "a clock time"),
    (rf"\b(within|in|by)\s+{NUM}\s*{UNIT}\b", "a deadline duration"),
    (r"\b(noon|midnight|close of business|end of business|cob|eod|next business day)\b", "a clock time or deadline"),
    (r"\b(deadline|due (by|on|date))\b", "a deadline"),
    (r"\b(tomorrow|tonight|next week|end of (the )?(day|week))\b", "a relative date"),
]
CLAIMS = [
    (r"\binspection (is |was |has been )?(complete|completed|closed)\b", "says the inspection is complete"),
    (r"\bmark(ed)? (as )?complete\b", "marks something complete"),
    (r"\b(signed|signature applied|e-?signed)\b", "claims a signature"),
    (r"\bcertif(y|ies|ied|ication)\b", "certifies"),
    (r"\b(in compliance|is compliant|fully compliant|meets all (permit )?requirements|no (permit |cgp )?violations?)\b", "makes a compliance determination"),
    (r"\bno (further |additional |corrective )?(action|maintenance|repairs?) (is |was |are )?(required|needed|necessary)\b", "says no action is needed"),
    (r"\b(inspection|site|work|repairs?|everything|controls?)\s+(is |was |has been |are |were )?(finished|done|good to go|all set|satisfactory|passed)\b", "says the work is finished or acceptable"),
    (r"\b(all set|good to go|passed (the )?inspection)\b", "says the work is finished or acceptable"),
]
CITATION = re.compile(r"§\s*(\d+(?:\.\d+)*)|\bsection\s+(\d+(?:\.\d+)+)\b|\bSWPPP\s+(\d+(?:\.\d+)+)\b", re.I)


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
        num = m.group(1) or m.group(2) or m.group(3)
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
    (r"\b(threshold|trigger)\b.*(\d|\binch|\bhalf\b|\bquarter\b)", "change the storm threshold"),
    (r"\b(say|state|write|declare|confirm|report)\b.*\b(passed|approved|finished|all set|satisfactory|no action)\b", "declare the site passed"),
    (r"\b(pretend|act as|role-?play|you are the inspector|as if you were)\b", "act as the inspector"),
    (r"\bapprov(e|al)\b", "approve the report"),
    (r"\b(leave out|omit|hide|drop|exclude|don'?t mention|do not mention|skip|remove)\b.*\b(deficienc|overdue|finding|flag|escalat|discharge|problem|issue|repair|damage|sediment|control|fence|bag|inlet|wattle|basin)", "leave out a finding"),
]


def check_request(instruction):
    text = (instruction or "").lower()
    for pattern, what in REFUSE:
        if re.search(pattern, text):
            return False, (f"I can't {what}. Dates come from the scheduler, records are read-only, "
                           f"and only the inspector reviews, signs, and files the report.")
    return True, ""
