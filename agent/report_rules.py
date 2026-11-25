"""Report-time rules that use the inspector's entries (Process Outline R8, R9). Plain Python, no AI.

  R8  CHECK_GAUGE: the station shows 0.15-0.24 in (near the trigger), the site has a manual
      rain gauge, and the gauge was not read. The inspector should read it.
  R8  POSSIBLE_MISSED_INSPECTION: the manual gauge shows 0.25 in or more but the station
      never triggered a storm inspection. Goes to the failure register for review.
  R9  Report due = actual inspection completion + 24 hours (continuous time, no weekend
      extension; team interpretation).
Not built (v1): a remotely readable site gauge does not override NOAA; see README.
"""
from agent.scheduler import plus_hours
from config import STORM_THRESHOLD_IN

CHECK_GAUGE_MIN_IN = 0.15


def has_manual_gauge(site):
    return str(site.get("has_manual_gauge", "no")).strip().lower() == "yes"


def gauge_flags(site, station_max_24h, gauge_in, station_triggered):
    """Flags from the station total and the site gauge. gauge_in is None if the gauge was not read."""
    flags = []
    if gauge_in is not None and gauge_in >= STORM_THRESHOLD_IN and not station_triggered:
        flags.append("POSSIBLE_MISSED_INSPECTION")
    if (gauge_in is None and has_manual_gauge(site)
            and CHECK_GAUGE_MIN_IN <= round(station_max_24h, 2) < STORM_THRESHOLD_IN):
        flags.append("CHECK_GAUGE")
    return flags


def report_due(completed_at):
    """R9: 24 real hours after the inspection was actually completed."""
    return plus_hours(completed_at, 24)
