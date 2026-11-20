"""Run the test suite in tests/cases.json and report pass rates. Plain Python, no AI.

Case types:
  schedule   site + rainfall -> storm triggers / due dates / routine due / flags      (scheduler.py)
  missing    rainfall with gaps -> MISSING_DATA true/false                            (rainfall.py, Option B)
  corrective deficiency -> category, first deadline, flags                            (corrective.py)
  validator  AI-style text -> pass/fail                                                (validator.check)
  request    revise-chat instruction -> allowed/refused                               (validator.check_request)
  swppp      site SWPPP -> threshold-conflict warning true/false                      (swppp.py)
Times in cases are site-local 'YYYY-MM-DD HH:MM'. Alex writes the expected answers from the permit.
"""
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent import corrective, swppp, validator
from agent.rainfall import missing_matters
from agent.scheduler import LOCAL, site_schedule
from config import DATA, ROOT

CASES_FILE = ROOT / "tests" / "cases.json"
FAILURE_REGISTER = DATA / "failure_register.csv"
BASE_SITE = {"site_id": "TEST", "frequency_option": "B", "impaired_water": "no",
             "last_inspection": "2026-11-09 08:00"}


def t(text):
    return datetime.fromisoformat(text).replace(tzinfo=LOCAL)


def fmt(dt):
    return dt.astimezone(LOCAL).strftime("%Y-%m-%d %H:%M") if dt else None


def hourly(case):
    start, end = t(case["window"][0]), t(case["window"][1])
    rain = {t(a): v for a, v in case.get("rain", [])}
    missing = {t(a) for a in case.get("missing", [])}
    rows, h = [], start
    while h <= end:
        if h in missing:
            rows.append({"hour_end_utc": h.astimezone(timezone.utc), "rain_in": None, "status": "missing"})
        else:
            rows.append({"hour_end_utc": h.astimezone(timezone.utc), "rain_in": rain.get(h, 0.0),
                         "status": "ok" if h in rain else "dry"})
        h += timedelta(hours=1)
    return rows


def run_case(case):
    kind, exp = case["type"], case["expected"]
    now = t(case.get("now", "2026-12-31 00:00")).astimezone(timezone.utc)
    if kind == "schedule":
        items = site_schedule({**BASE_SITE, **case.get("site", {})}, hourly(case), now)
        storms = [i for i in items if i["kind"].startswith("Storm")]
        actual = {"storm": [{"trigger": fmt(s["trigger"]), "due": fmt(s["due"]),
                             **({"alt_due": fmt(s["alt_due"])} if s["alt_due"] else {})} for s in storms],
                  "routine_due": fmt([i for i in items if i["kind"] == "Routine"][0]["due"]),
                  "flags": sorted({f for i in items for f in i["flags"]})}
        ok = True
        if "storm" in exp:
            ok &= [{k: v for k, v in s.items() if k in ("trigger", "due", "alt_due")} for s in actual["storm"]] == exp["storm"]
        if "routine_due" in exp:
            ok &= actual["routine_due"] == exp["routine_due"]
        for f in exp.get("flags_include", []):
            ok &= f in actual["flags"]
        return ok, actual
    if kind == "missing":
        actual = missing_matters(hourly(case), now)
        return actual == exp["missing_flag"], {"missing_flag": actual}
    if kind == "corrective":
        info = corrective.deficiency_deadlines(case["deficiency"], {**BASE_SITE, **case.get("site", {})},
                                               case.get("history", []), now)
        actual = {"category": info["category"], "first_deadline": fmt(info["deadlines"][0][1]),
                  "flags": info["flags"]}
        ok = actual["category"] == exp.get("category", actual["category"])
        ok &= actual["first_deadline"] == exp.get("first_deadline", actual["first_deadline"])
        for f in exp.get("flags_include", []):
            ok &= f in actual["flags"]
        for f in exp.get("flags_exclude", []):
            ok &= f not in actual["flags"]
        return ok, actual
    if kind == "validator":
        passed, problems = validator.check(case["text"], set(case.get("sections", [])))
        return passed == exp["pass"], {"pass": passed, "problems": problems}
    if kind == "request":
        allowed, reason = validator.check_request(case["text"])
        return allowed == exp["allowed"], {"allowed": allowed, "reason": reason}
    if kind == "swppp":
        warnings = swppp.threshold_conflicts(case["site_id"])
        return bool(warnings) == exp["warning"], {"warning": bool(warnings), "messages": warnings}
    return False, {"error": f"unknown case type {kind}"}


def run_all(path=CASES_FILE):
    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    results = []
    for c in cases:
        try:
            ok, actual = run_case(c)
        except Exception as e:                     # a crash is a failure, not a stop
            ok, actual = False, {"error": f"{e.__class__.__name__}: {e}"}
        results.append({"id": c["id"], "label": c["label"], "type": c["type"], "rule": c.get("rule", ""),
                        "description": c["description"], "passed": bool(ok),
                        "expected": json.dumps(c["expected"]), "actual": json.dumps(actual, default=str)})
    return results


def save_failures(results):
    """Append failed cases to data/failure_register.csv (cause and fix columns left for the team)."""
    failed = [r for r in results if not r["passed"]]
    new = not FAILURE_REGISTER.exists()
    with FAILURE_REGISTER.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["run_at", "case_id", "label", "rule", "description", "expected", "actual", "cause", "fix"])
        stamp = datetime.now(LOCAL).strftime("%Y-%m-%d %H:%M")
        for r in failed:
            w.writerow([stamp, r["id"], r["label"], r["rule"], r["description"], r["expected"], r["actual"], "", ""])
    return len(failed)


if __name__ == "__main__":
    res = run_all()
    for r in res:
        print(("PASS" if r["passed"] else "FAIL"), r["id"], r["label"], r["description"])
    print(f"{sum(r['passed'] for r in res)}/{len(res)} passed")
