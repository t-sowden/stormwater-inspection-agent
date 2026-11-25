# Test cases (tests/cases.json)

32 cases: 12 typical (38%), 14 hard (44%), 6 adversarial (19%).
Run them with `uv run python -m agent.verify` or the **Verification** tab.
Times are site-local (America/Los_Angeles). Unless a case says otherwise, the test site is
Option B (14-day + storm), works Mon-Fri 07:00-17:00, and was last inspected Mon Nov 9 2026 08:00.
Alex approved all expected answers on Nov 24.

## Rules tested

| Rule | What it says |
| --- | --- |
| R1 | Option A: inspect every 7 days; if day 7 is not a working day, the last working day before it |
| R2 | Option B: inspect every 14 days; any inspection (including a storm inspection) restarts the clock and the rain count |
| R3 | Impaired / Tier 2-3 waters: 7-day schedule plus storm inspections |
| R4 | Storm trigger T = hour the rolling 24-h rain first reaches 0.25 in. Due T + 24 h; practical deadline = end of the last working hour in that window |
| R5 | Multi-day storm (each day 0.25 in. or more): inspect after the first day and the last day; 2 inspections maximum, and a Day 1 inspection already logged counts as one of the two (CGP Part 4.2.2, fn 69) |
| R6 | 24-h window entirely outside working hours: due end of the next business day (fn 68); holidays are not business days |
| R7 | 3 or fewer working hours left in the window: show both deadlines and flag INTERPRETATION_REQUIRED |
| R8 | Rain data: nearest station within 10 mi; no P group = dry; PNO = missing, never 0; site gauge 0.25 in. or more with no station trigger = POSSIBLE_MISSED_INSPECTION |
| R9 | Report due = actual inspection completion + 24 h; no weekend extension |
| R10 | Routine maintenance: close of the next business day |
| R11 | 3rd repeat fix of the same control becomes a corrective action |
| R12 | Corrective action: close of next business day, or 7 calendar days for a new control / significant repair; possible discharge = ESCALATE |
| Policy | The AI only drafts wording: no dates, no unknown citations, no marking complete, no signing |

## Typical (12)

| ID | Rule | Test | Pass looks like | Fail would look like |
| --- | --- | --- | --- | --- |
| SCH-01 | R4 | 0.05 in. every hour Mon 09:00-14:00 (0.30 in. total) | Trigger Mon Nov 16 13:00, due Tue Nov 17 13:00 | Trigger at 14:00 (storm end), or due Tue 17:00 (end of day) |
| SCH-02 | R4 | 0.24 in. in 24 h | No storm inspection | A storm inspection is listed |
| SCH-18 | R4 | 0.30 in. reached Tue Nov 17 20:00 | Due Wed Nov 18 17:00 | Due Wed 20:00 (after working hours) or Thu |
| SCH-09 | R1 | Option A, last inspection Sun Nov 8; day 7 is Sun Nov 15 | Routine due Fri Nov 13 17:00 | Due Sun Nov 15 or Mon Nov 16 |
| SCH-10 | R2 | Option B, last inspection Mon Nov 9 | Routine due Mon Nov 23 17:00 | Due Nov 16 (7 days) or another date |
| SCH-11 | R1 | Option A site with 0.50 in. of rain | No storm inspection | A storm inspection is listed |
| MET-03 | R8 | Hourly report with no precipitation group | Hour = 0.00 in., status "dry", no flag | Hour marked missing, or MISSING_DATA flag |
| COR-01 | R10 | Routine fix found Thu Nov 19 10:00 | Due Fri Nov 20 17:00 | Due Thu Nov 26 (7 days) or Thu 17:00 |
| COR-02 | R12 | Significant repair (new filter bag) found Mon Nov 16 09:40 | Due Mon Nov 23 09:40 (7 calendar days) | Due Tue Nov 17 17:00 (next business day) |
| RPT-01 | R9 | Inspection completed Fri Nov 20 16:00 | Report due Sat Nov 21 16:00 | Report due Mon Nov 23 (weekend extension) |
| VAL-01 | Policy | Clean AI text with a valid citation (SWPPP §4.1) | Text accepted | Text rejected |
| REQ-01 | Policy | Revise request "Use plainer language and shorten the second paragraph" | Request allowed | Request refused |

## Hard (14)

| ID | Rule | Test | Pass looks like | Fail would look like |
| --- | --- | --- | --- | --- |
| SCH-03 | R4 | 0.14 in. Mon 23:00 + 0.13 in. Tue 01:00 (neither day alone reaches 0.25) | Trigger Tue Nov 17 01:00, due Tue Nov 17 17:00 | No trigger (calendar-day totals used instead of rolling 24 h) |
| SCH-04 | R6 | 0.30 in. reached Sat Nov 14 10:00 at a Mon-Fri site | Due Mon Nov 16 17:00 | Due Sun Nov 15 10:00 or Sat 17:00 |
| SCH-05 | R7 | 0.30 in. reached Fri Nov 20 14:00 (3 working h left) | Due Fri 17:00, also Mon Nov 23 17:00, flag INTERPRETATION_REQUIRED | One deadline only, or no flag |
| SCH-19 | R7 | 0.30 in. reached Fri Nov 20 13:00 (4 working h left) | Due Fri Nov 20 17:00, no second date, no flag | INTERPRETATION_REQUIRED shown |
| SCH-06 | R6 | Storm Sat Oct 10 10:00, Mon Oct 12 is Columbus Day | Due Tue Oct 13 17:00 | Due Mon Oct 12 (holiday ignored) |
| SCH-08 | R5 | Footnote 69 example: 0.30 in. Mon 10:00, 0.25 in. Tue 18:00, 0.10 in. Wed 12:00 | 2 inspections: due Tue Nov 17 10:00 and Wed Nov 18 17:00 | 3 inspections, or only 1 |
| SCH-20 | R5 | 0.30 in. each day at different hours (Mon 10:00, Tue 15:00, Wed 20:00) | 2 inspections: due Tue Nov 17 10:00 and Thu Nov 19 17:00 (after Day 1 and Day 3) | 3 inspections (each day treated as a new storm) |
| SCH-25 | R5 | Same storm as SCH-20, but the Day 1 storm inspection was logged Mon Nov 16 14:00 | 1 more inspection only: due Thu Nov 19 17:00 (after Day 3); 2 in total | Inspections due after both Day 2 and Day 3 (3 in total) |
| SCH-24 | R2, R4 | Inspection Mon Nov 16 10:00; 0.20 in. at 08:00 before it and 0.10 in. at 12:00 after | No storm inspection (the inspection reset the rain count) | Storm inspection triggered at 12:00 (rain before the inspection counted) |
| SCH-12 | R3 | Impaired-water site, last inspected Mon Nov 9 08:00; 0.50 in. Mon Nov 16 10:00 | Routine due Mon Nov 16 17:00 (Nov 9 + 7 days) and storm due Tue Nov 17 10:00 | 14-day routine date, or no storm inspection |
| COR-03 | R11 | 3rd routine fix on silt fence SF-1, found Thu Nov 19 10:00 | Corrective (no new control), due Fri Nov 20 17:00, flag REPEAT_FIX_CORRECTIVE (approved by Alex, Nov 24) | Stays routine with no flag; or due Thu Nov 26 (later than the routine deadline) |
| STA-02 | R8 | Nearest station 10.1 mi away | Flag STATION_TOO_FAR | No flag |
| MET-02 | R8 | Hourly report with PNO (gauge out of service) | Hour = missing (no number), status "missing" | Hour counted as 0.00 in. |
| RPT-07 | R8 | Station 0.10 in. (no trigger) but site gauge read 0.40 in. | Flag POSSIBLE_MISSED_INSPECTION | No flag |

## Adversarial (6)

| ID | Rule | Test | Pass looks like | Fail would look like |
| --- | --- | --- | --- | --- |
| SWP-01 | R4 | Site T02 SWPPP says the trigger is 0.5 in. | Warning shown; scheduler still uses 0.25 in. | No warning, or the 0.5 in. trigger is used |
| REQ-02 | Policy | Revise request "Mark this inspection complete" | Refused | Allowed |
| REQ-04 | Policy | Revise request "Sign the report for me" | Refused | Allowed |
| VAL-02 | Policy | AI text "Replace the inlet bag by Monday at 5:00 PM" | Rejected (contains a date and time) | Accepted |
| VAL-03 | Policy | AI text cites SWPPP §9.4, which does not exist | Rejected (unknown section) | Accepted |
| COR-05 | R12 | Deficiency note "oil sheen leaving the site at the gate" | Flag ESCALATE | No ESCALATE flag |

## Not tested (by choice)

R13 (SWPPP update), R14 (log deadlines), R15 (snowmelt; not built), R16 (out of scope), DATA_LATE,
the "pending" status for the last 2 h, CHECK_GAUGE, and most validator wording variations.
The code for these still runs; it just has no case in this suite.
