"""Corrective-action and maintenance deadlines (Process Outline R10-R14). Plain Python, no AI.

Categories (assigned by the inspector, never by the agent):
  routine_maintenance        R10: finish by close of the next business day
                                  (if infeasible and documented: within 7 calendar days of discovery)
  corrective_no_new_control  R12: close of the next business day
  corrective_new_control     R12: within 7 calendar days of discovery (new/replacement control or
                                  significant repair); R13: update the SWPPP within 7 days of completion
R11: the 3rd or later routine fix of the same control becomes a corrective action. The agent uses
     the earlier corrective deadline (close of next business day) and flags REPEAT_FIX_CORRECTIVE so
     the inspector picks the final category (a new control would allow 7 days).
R14: record the condition within 24 h of finding it; record the actions within 24 h of completing them.
A description mentioning a possible discharge or water-quality issue is flagged ESCALATE.
"""
from datetime import datetime, timedelta, timezone

from agent.scheduler import LOCAL, calendar_for, plus_hours

CATEGORIES = {
    "routine_maintenance": "Routine maintenance",
    "corrective_no_new_control": "Corrective action (no new control)",
    "corrective_new_control": "Corrective action (new control or significant repair)",
}
ESCALATE_WORDS = ("discharge", "sheen", "turbid", "plume", "leaving the site", "offsite", "off-site",
                  "muddy water", "sediment in the street", "sediment on the street", "tracked onto",
                  "into the inlet", "street inlet", "storm drain", "into the creek", "into the stream")


def parse_local(text):
    return datetime.fromisoformat(text).replace(tzinfo=LOCAL) if text else None


def deficiency_deadlines(defect, site, history=(), now=None):
    """Deadlines for one deficiency.

    defect: dict with control_id, found_at, description, category, status, closed_at.
    history: earlier deficiencies for the same site (used for the R11 repeat count).
    Returns dict: category, deadlines [(label, datetime, rule)], flags.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(LOCAL)
    cal = calendar_for(site)
    found = parse_local(defect["found_at"])
    closed = parse_local(defect.get("closed_at", ""))
    category = defect["category"]
    flags, deadlines = [], []

    if category == "routine_maintenance":
        repeats = [h for h in history if h["control_id"] == defect["control_id"]
                   and h["category"] == "routine_maintenance"
                   and parse_local(h["found_at"]) < found]
        if len(repeats) >= 2:
            flags.append("REPEAT_FIX_CORRECTIVE")
            category = "corrective_no_new_control"   # never later than the routine deadline

    if category == "routine_maintenance":
        deadlines.append(("Finish maintenance", cal.next_business_day_end(found.date()), "R10"))
        deadlines.append(("If infeasible (documented)", found + timedelta(days=7), "R10"))
    elif category == "corrective_no_new_control":
        deadlines.append(("Complete corrective action", cal.next_business_day_end(found.date()), "R12"))
    elif category == "corrective_new_control":
        deadlines.append(("Complete corrective action", found + timedelta(days=7), "R12"))
        if closed:
            deadlines.append(("Update SWPPP", closed + timedelta(days=7), "R13"))
    else:
        flags.append("UNKNOWN_CATEGORY")

    deadlines.append(("Record condition in log", plus_hours(found, 24), "R14"))
    if closed:
        deadlines.append(("Record actions in log", plus_hours(closed, 24), "R14"))

    if any(w in defect.get("description", "").lower() for w in ESCALATE_WORDS):
        flags.append("ESCALATE")
    if defect.get("status", "open") == "open":
        main = deadlines[0][1]
        if main < now:
            flags.append("OVERDUE")

    return {"category": category, "deadlines": deadlines, "flags": flags}


def open_items(site, defects, now=None):
    """Open deficiencies for a site with their deadlines, earliest first."""
    out = []
    for d in defects:
        if d.get("status", "open") != "open":
            continue
        history = [h for h in defects if h is not d]
        info = deficiency_deadlines(d, site, history, now)
        out.append({**d, **info})
    return sorted(out, key=lambda x: x["deadlines"][0][1])
