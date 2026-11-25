"""Construction Stormwater Inspection Agent - Streamlit dashboard."""
import time as clock
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

from agent import corrective, drafter, records, report_rules, swppp, validator
from agent import verify as verifier
from agent.rainfall import load_cache, rain_for_station, storm_trigger
from agent.scheduler import site_schedule, storm_triggers
from agent.stations import nearest_station
from config import (LAST_REFRESH_FILE, MAX_STATION_MI, OLLAMA_HOST, OLLAMA_MODEL,
                    SITE_STATIONS_FILE, SITE_TZ, SITES_FILE, STORM_THRESHOLD_IN)
from agent.scheduler import LOCAL as SCHED_LOCAL

LOCAL = ZoneInfo(SITE_TZ)
st.set_page_config(page_title="Stormwater Inspection Agent", layout="wide")


# ---------- Helpers ----------
def ollama_status():
    """Return (connected, list of model names) for the local Ollama server."""
    try:
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
        r.raise_for_status()
        return True, [m["name"] for m in r.json().get("models", [])]
    except requests.RequestException:
        return False, []


def test_ollama():
    """Send one short prompt to the local model. Returns (reply, seconds) or raises."""
    start = clock.time()
    r = requests.post(f"{OLLAMA_HOST}/api/generate", timeout=300, json={
        "model": OLLAMA_MODEL, "stream": False,
        "prompt": "In one sentence, confirm you are a local AI model ready to help "
                  "draft construction stormwater inspection reports."})
    r.raise_for_status()
    return r.json().get("response", "").strip(), clock.time() - start


def local_time(ts):
    """Datetime -> readable local time, e.g. 'Mon Nov 9 2:00 PM'."""
    if ts is None:
        return ""
    return ts.astimezone(LOCAL).strftime("%a %b %d %I:%M %p").replace(" 0", " ")


def load_sites():
    """Active sites from data/sites.csv."""
    sites = pd.read_csv(SITES_FILE, dtype=str).fillna("")
    sites["lat"] = sites["lat"].astype(float)
    sites["lon"] = sites["lon"].astype(float)
    return sites[sites["active"].str.lower() == "yes"].reset_index(drop=True)


def load_site_stations():
    """Saved site -> station lookup from the last refresh (empty if never refreshed)."""
    if SITE_STATIONS_FILE.exists():
        return pd.read_csv(SITE_STATIONS_FILE, dtype={"site_id": str}).set_index("site_id")
    return pd.DataFrame()


def last_refresh():
    """When rainfall was last refreshed, or None."""
    if LAST_REFRESH_FILE.exists():
        return datetime.fromisoformat(LAST_REFRESH_FILE.read_text().strip())
    return None


# ---------- The only place the weather API is called ----------
def refresh_rainfall(sites):
    """Find each site's station, download 7 days of rain per station, save to cache."""
    progress = st.progress(0.0, text="Finding nearest stations...")
    lookup, errors = [], []
    for i, site in sites.iterrows():
        try:
            station, flags = nearest_station(site["lat"], site["lon"])
            lookup.append({
                "site_id": site["site_id"],
                "station_id": station["station_id"] if station else "",
                "station_name": station["name"] if station else "",
                "station_lat": station["lat"] if station else None,
                "station_lon": station["lon"] if station else None,
                "distance_mi": station["distance_mi"] if station else None,
                "station_flags": ";".join(flags),
            })
        except Exception as e:
            errors.append(f"{site['site_id']}: station lookup failed - {e.__class__.__name__}: {str(e)[:200]}")
        progress.progress((i + 1) / (2 * len(sites)), text="Finding nearest stations...")

    stations = sorted({row["station_id"] for row in lookup if row["station_id"]})
    for j, station_id in enumerate(stations):
        try:
            rain_for_station(station_id)
        except Exception as e:
            errors.append(f"{station_id}: rainfall download failed - {e.__class__.__name__}: {str(e)[:200]}")
        progress.progress(0.5 + (j + 1) / (2 * max(len(stations), 1)),
                          text=f"Downloading rainfall for {station_id}...")

    if lookup:
        SITE_STATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(lookup).to_csv(SITE_STATIONS_FILE, index=False)
    LAST_REFRESH_FILE.write_text(datetime.now(timezone.utc).isoformat())
    progress.empty()
    return errors


# ---------- Triage table (reads saved data only) ----------
PRIORITY_ORDER = {"OVERDUE": 0, "STORM INSPECTION": 1, "CHECK DATA": 2, "Routine": 3}


def scheduler_trigger(site_d, hourly):
    """First 0.25-in trigger since the last inspection, from the same scheduler function that sets
    the due dates (so the table and the due dates can never disagree)."""
    last = str(site_d.get("last_inspection", "")).strip()
    if not last:
        return None
    triggers = storm_triggers(hourly, datetime.fromisoformat(last).replace(tzinfo=SCHED_LOCAL))
    return triggers[0][0] if triggers else None


def build_triage(sites, site_stations, now=None):
    now = now or datetime.now(timezone.utc)
    rows, problems = [], []
    for _, site in sites.iterrows():
        sid = site["site_id"]
        if sid not in site_stations.index or not site_stations.loc[sid, "station_id"]:
            rows.append({"Priority": "CHECK DATA", "Site": sid, "Name": site["name"],
                         "Flags": "NO_STATION_DATA", "_due": now + timedelta(days=365)})
            continue
        st_row = site_stations.loc[sid]
        hourly = [r for r in load_cache(st_row["station_id"])
                  if r["hour_end_utc"] > now - timedelta(days=7)]
        _, max_24h, data_flags = storm_trigger(hourly, now=now)
        if isinstance(st_row["station_flags"], str) and st_row["station_flags"]:
            data_flags = data_flags + st_row["station_flags"].split(";")
        site_d = site.to_dict()
        site_d["last_inspection"] = records.last_inspection(sid, site_d.get("last_inspection", ""))
        trigger = scheduler_trigger(site_d, hourly)
        fixes = corrective.open_items(site_d, records.deficiencies(sid), now)
        try:
            items = site_schedule(site_d, hourly, now)
        except Exception as e:
            problems.append(f"{sid}: could not compute due dates - {e.__class__.__name__}: {e}")
            continue

        nxt = items[0]
        flags = sorted(set(data_flags + [f for it in items for f in it["flags"]]
                           + [f for fx in fixes for f in fx["flags"]]))
        if "OVERDUE" in flags:
            priority = "OVERDUE"
        elif any(it["kind"].startswith("Storm") for it in items):
            priority = "STORM INSPECTION"
        elif flags:
            priority = "CHECK DATA"
        else:
            priority = "Routine"

        also = []
        for it in items:
            if it["alt_due"]:
                also.append(f"EPA intent: {local_time(it['alt_due'])}")
        for it in items[1:]:
            also.append(f"{it['kind']}: {local_time(it['due'])}")

        rows.append({
            "Priority": priority,
            "Site": sid,
            "Name": site["name"],
            "Next due": local_time(nxt["due"]),
            "Due for": nxt["kind"],
            "Rule": nxt["rule"],
            "Station": st_row["station_id"],
            "Distance (mi)": st_row["distance_mi"],
            "Max 24-h rain (in)": round(max_24h, 2),
            "0.25 in reached (since last insp.)": local_time(trigger),
            "Also due": "; ".join(also),
            "Open fixes": len(fixes),
            "Flags": ", ".join(flags),
            "_due": nxt["due"],
        })
    table = pd.DataFrame(rows)
    table["_p"] = table["Priority"].map(PRIORITY_ORDER)
    table = table.sort_values(["_p", "_due"]).drop(columns=["_p", "_due"])
    return table, problems


def color_priority(value):
    colors = {"OVERDUE": "background-color: #f1aeb5",
              "STORM INSPECTION": "background-color: #f8d7da",
              "CHECK DATA": "background-color: #fff3cd",
              "Routine": "background-color: #d1e7dd"}
    return colors.get(value, "")



# ---------- Shared site context (saved data only) ----------
CONDITIONS = {
    "OK": None,
    "Routine maintenance": "routine_maintenance",
    "Corrective action (no new control)": "corrective_no_new_control",
    "Corrective action (new control or significant repair)": "corrective_new_control",
}


def long_time(ts):
    return ts.astimezone(LOCAL).strftime("%a %b %d, %Y %I:%M %p").replace(" 0", " ") if ts else ""


def site_context(site, site_stations, now=None):
    """Everything the checklist and report need for one site, from saved data only."""
    now = now or datetime.now(timezone.utc)
    sid = site["site_id"]
    site_d = site.to_dict()
    site_d["last_inspection"] = records.last_inspection(sid, site_d.get("last_inspection", ""))
    controls = [c for c in str(site_d.get("control_ids", "")).split(";") if c]
    rain = {"station": "none", "distance_mi": "n/a", "max_24h_in": 0.0, "trigger": "none", "flags": ["NO_STATION_DATA"]}
    hourly = []
    if not site_stations.empty and sid in site_stations.index and site_stations.loc[sid, "station_id"]:
        st_row = site_stations.loc[sid]
        hourly = [r for r in load_cache(st_row["station_id"]) if r["hour_end_utc"] > now - timedelta(days=7)]
        _, max_24h, flags = storm_trigger(hourly, now=now)
        trig = scheduler_trigger(site_d, hourly)
        if isinstance(st_row["station_flags"], str) and st_row["station_flags"]:
            flags = flags + st_row["station_flags"].split(";")
        rain = {"station": st_row["station_id"], "distance_mi": st_row["distance_mi"],
                "max_24h_in": round(max_24h, 2), "trigger": long_time(trig) or "none", "flags": flags}
    items = site_schedule(site_d, hourly, now) if site_d["last_inspection"] else []
    fixes = corrective.open_items(site_d, records.deficiencies(sid), now)
    return {"site": site_d, "controls": controls, "rain": rain, "items": items, "fixes": fixes}


def fixes_table(fixes):
    return pd.DataFrame([{
        "ID": f["deficiency_id"], "Control": f["control_id"], "Description": f["description"],
        "Category": corrective.CATEGORIES.get(f["category"], f["category"]),
        "Action": f["deadlines"][0][0], "Deadline": long_time(f["deadlines"][0][1]),
        "Rule": f["deadlines"][0][2], "Flags": ", ".join(f["flags"])} for f in fixes])


def build_facts(ctx, form, now=None):
    """Python computes every date and flag for the report. The AI never sees dates."""
    site, sid = ctx["site"], ctx["site"]["site_id"]
    insp_time = datetime.combine(form["date"], form["time"]).replace(tzinfo=LOCAL)
    history = records.deficiencies(sid)
    findings, flags = [], set(ctx["rain"]["flags"])
    for sec in swppp.sections_for(sid, ctx["controls"]):
        cond = form["conditions"].get(sec["control_id"], "OK")
        note = form["notes"].get(sec["control_id"], "").strip()
        f = {"control_id": sec["control_id"], "title": sec["title"], "citation": f"SWPPP §{sec['number']}",
             "condition": cond, "notes": note, "category_label": "No action", "deadlines": [], "flags": []}
        if CONDITIONS[cond]:
            info = corrective.deficiency_deadlines(
                {"control_id": sec["control_id"], "found_at": insp_time.strftime("%Y-%m-%d %H:%M"),
                 "description": note, "category": CONDITIONS[cond], "status": "open"}, site, history, now)
            f["category_label"] = corrective.CATEGORIES[info["category"]]
            f["deadlines"] = [(lbl, long_time(when), rule) for lbl, when, rule in info["deadlines"]]
            f["flags"] = [x for x in info["flags"] if x != "OVERDUE"]
            flags.update(f["flags"])
        findings.append(f)
    if form["discharge"]:
        flags.add("ESCALATE")
        findings.append({"control_id": "General", "title": "Possible discharge", "citation": "CGP 5.1",
                         "condition": "Observed", "notes": form["discharge_note"].strip(),
                         "category_label": "Escalate to compliance manager", "flags": ["ESCALATE"],
                         "deadlines": [("Notify compliance manager", "Immediately", "R12")]})
    gauge = form["gauge"] if form["gauge_read"] else None
    station_triggered = any(i["kind"].startswith("Storm") for i in ctx["items"])
    flags.update(report_rules.gauge_flags(site, ctx["rain"]["max_24h_in"], gauge, station_triggered))
    flags.update(f"SWPPP_CONFLICT: {w}" for w in swppp.threshold_conflicts(sid))
    return {
        "site_id": sid, "site_name": site["name"], "inspector": form["inspector"].strip(),
        "inspection_type": form["type"], "inspection_time": long_time(insp_time),
        "report_due": long_time(report_rules.report_due(insp_time)),
        "weather_notes": form["weather"].strip(), "rainfall": ctx["rain"], "gauge_reading": gauge,
        "findings": findings, "flags": sorted(flags),
        "open_items": [{**fx, "deadlines": [(l, long_time(w), r) for l, w, r in fx["deadlines"]]}
                       for fx in ctx["fixes"]],
        "sections": sorted(swppp.section_ids(sid)),
    }


def write_narrative(facts, previous=None, instruction=None):
    """AI narrative if Ollama is up and the validator passes; otherwise the Python template."""
    try:
        text = drafter.ollama_narrative(facts, previous, instruction)
    except requests.RequestException as e:
        problems, reason = [f"Local AI unavailable ({e.__class__.__name__}). Is the Ollama app running?"], "local AI unavailable"
    else:
        ok, problems = validator.check(text, set(facts["sections"]))
        if ok:
            return text, "AI-drafted, validated", []
        reason = "AI draft failed validation"
    if previous is not None:
        return previous, "unchanged", problems
    return drafter.template_narrative(facts), f"Python template: {reason}", problems


# ---------- Page ----------
connected, models = ollama_status()
sites = load_sites()

with st.sidebar:
    st.header("System status")
    if not connected:
        st.error("Ollama not reachable at localhost:11434. Start the Ollama app.")
    elif not any(m.startswith(OLLAMA_MODEL) for m in models):
        st.warning(f"Model missing. Run: ollama pull {OLLAMA_MODEL}")
    else:
        st.success(f"Ollama connected: {OLLAMA_MODEL}")
    refreshed = last_refresh()
    st.caption(f"**Rainfall last refreshed:** {local_time(refreshed) if refreshed else 'Never'}")
    replay = st.checkbox("Replay: judge everything as of the last refresh", value=False,
                         disabled=refreshed is None,
                         help="For offline demos with saved data. DATA_LATE, OVERDUE and due dates are "
                              "computed as if it were the moment of the last refresh, not now.")
    AS_OF = refreshed if (replay and refreshed) else None
    if AS_OF:
        st.info(f"Replay mode: times judged as of {local_time(AS_OF)}.")
    st.caption(f"Active sites: {len(sites)}  |  Max station distance: {MAX_STATION_MI} mi  |  "
               f"Storm threshold: {STORM_THRESHOLD_IN} in / 24 h  |  Times: {SITE_TZ}")

    with st.expander("Test local AI"):
        st.caption("Sends one short prompt to Ollama on this PC. No internet. "
                   "The first run can take a minute while the model loads.")
        if st.button("Send test prompt", disabled=not connected):
            with st.spinner("Waiting for the local model..."):
                try:
                    reply, secs = test_ollama()
                    st.success(f"Reply in {secs:.1f} s")
                    st.write(reply)
                except requests.RequestException as e:
                    st.error(f"Ollama test failed - {e.__class__.__name__}: {str(e)[:200]}")

st.title("Construction Stormwater Inspection Agent")
st.caption("DRAFT tool. Inspector review required. The agent never completes, "
           "signs, or edits inspection records.")

triage, checklist, report, verify = st.tabs(
    ["Storm Triage", "Site Checklist", "Draft Report", "Verification"])

with triage:
    left, right = st.columns([1, 3])
    with left:
        if st.button("Refresh rainfall", type="primary", width="stretch"):
            st.session_state["refresh_errors"] = refresh_rainfall(sites)
            st.session_state["refresh_done"] = True
            st.rerun()
    with right:
        st.caption("Rainfall comes from saved data. Only **Refresh rainfall** contacts NOAA "
                   "(last 7 days of hourly reports for each site's nearest station).")

    if st.session_state.pop("refresh_done", False):
        errors = st.session_state.get("refresh_errors", [])
        if errors:
            for err in errors:
                st.error(err)
        else:
            st.success("Rainfall refreshed.")

    site_stations = load_site_stations()
    if site_stations.empty:
        st.info("No rainfall data yet. Click **Refresh rainfall**.")
    else:
        table, problems = build_triage(sites, site_stations, AS_OF)
        for msg in problems:
            st.error(msg)
        st.dataframe(table.style.map(color_priority, subset=["Priority"]),
                     hide_index=True, width="stretch",
                     column_config={
                         "Distance (mi)": st.column_config.NumberColumn(format="%.1f"),
                         "Max 24-h rain (in)": st.column_config.NumberColumn(format="%.2f"),
                     })
        st.caption("Due dates come from scheduler.py (CGP rules R1-R7) using each site's working hours "
                   "and federal holidays; R7 shows both the literal deadline and EPA's next-business-day "
                   "intent. Last inspections and open fixes come from the read-only log "
                   "(data/inspections.csv, data/deficiencies.csv); OVERDUE includes overdue fixes (R10-R14).")

        map_sites = sites[["lat", "lon"]].assign(color="#1f6f8b", size=60)
        stations = site_stations.dropna(subset=["station_lat"])
        map_stations = pd.DataFrame({"lat": stations["station_lat"], "lon": stations["station_lon"],
                                     "color": "#d9534f", "size": 90})
        st.subheader("Sites (blue) and weather stations (red)")
        st.map(pd.concat([map_sites, map_stations]), latitude="lat", longitude="lon",
               color="color", size="size")

site_ids = list(sites["site_id"])
site_label = {r["site_id"]: f"{r['site_id']}  {r['name']}" for _, r in sites.iterrows()}
stations_saved = load_site_stations()

with checklist:
    sid = st.selectbox("Site", site_ids, format_func=site_label.get, key="ck_site")
    ctx = site_context(sites[sites["site_id"] == sid].iloc[0], stations_saved, AS_OF)
    for w in swppp.threshold_conflicts(sid):
        st.warning(w)
    if not swppp.load_sections(sid):
        st.error(f"No SWPPP found at data/swppps/{sid}.md.")
    c1, c2, c3 = st.columns(3)
    c1.metric("Last inspection", ctx["site"]["last_inspection"] or "none logged")
    nxt = ctx["items"][0] if ctx["items"] else None
    c2.metric("Next due", local_time(nxt["due"]) if nxt else "n/a", nxt["kind"] if nxt else None)
    c3.metric("Open fixes", len(ctx["fixes"]))
    if ctx["fixes"]:
        st.subheader("Open deficiencies (read-only log)")
        st.dataframe(fixes_table(ctx["fixes"]), hide_index=True, width="stretch")
    rows = swppp.checklist(sid, ctx["controls"], [f["control_id"] for f in ctx["fixes"]])
    st.subheader("Inspection checklist")
    st.caption("Built by Python from the site's SWPPP; every item cites its section. Ticks here are a "
               "field aid only and are not saved as records.")
    df = pd.DataFrame(rows).rename(columns={"citation": "Citation", "control_id": "Control", "item": "Check", "note": "Note"})
    df.insert(0, "Done", False)
    st.data_editor(df, hide_index=True, width="stretch", disabled=["Citation", "Control", "Check", "Note"], key=f"ck_{sid}")
    md = "\n".join([f"# Inspection checklist: {site_label[sid]}", ""] +
                   [f"- [ ] {r['item']} ({r['citation']}){' - ' + r['note'] if r['note'] else ''}" for r in rows])
    st.download_button("Download checklist (.md)", md, file_name=f"checklist_{sid}.md")

with report:
    sid = st.selectbox("Site", site_ids, format_func=site_label.get, key="rp_site")
    ctx = site_context(sites[sites["site_id"] == sid].iloc[0], stations_saved, AS_OF)
    sections = swppp.sections_for(sid, ctx["controls"])
    with st.form(f"findings_{sid}"):
        st.subheader("Inspection findings (entered by the inspector)")
        a, b, c = st.columns(3)
        inspector = a.text_input("Inspector")
        itype = b.selectbox("Inspection type", ["routine", "storm"])
        now_local = datetime.now(LOCAL)
        idate = c.date_input("Inspection date", now_local.date())
        itime = c.time_input("Inspection time", now_local.time().replace(second=0, microsecond=0))
        weather = st.text_area("Weather and general site notes", height=70)
        g1, g2 = st.columns(2)
        gauge_read = g1.checkbox("Site rain gauge was read")
        gauge = g2.number_input("Gauge reading (in)", min_value=0.0, step=0.01, format="%.2f")
        conds, notes = {}, {}
        for sec in sections:
            x, y = st.columns([1, 2])
            conds[sec["control_id"]] = x.selectbox(f"{sec['title']} (SWPPP §{sec['number']})", list(CONDITIONS),
                                                   key=f"c_{sid}_{sec['control_id']}")
            notes[sec["control_id"]] = y.text_input("Notes", key=f"n_{sid}_{sec['control_id']}")
        d1, d2 = st.columns([1, 2])
        discharge = d1.checkbox("Possible discharge or water-quality issue observed")
        discharge_note = d2.text_input("Describe what was seen")
        submitted = st.form_submit_button("Draft report", type="primary")
    if submitted:
        form = {"inspector": inspector, "type": itype, "date": idate, "time": itime, "weather": weather,
                "gauge_read": gauge_read, "gauge": gauge, "conditions": conds, "notes": notes,
                "discharge": discharge, "discharge_note": discharge_note}
        facts = build_facts(ctx, form, AS_OF)
        with st.spinner("Drafting with the local AI..."):
            text, source, problems = write_narrative(facts)
        st.session_state["draft"] = {"site": sid, "facts": facts, "narrative": text, "source": source,
                                     "problems": problems, "chat": []}

    draft = st.session_state.get("draft")
    if draft and draft["site"] == sid:
        if draft["problems"]:
            with st.expander("Why the AI draft was not used", expanded=False):
                for p in draft["problems"]:
                    st.write("- " + p)
        report_md = drafter.assemble_report(draft["facts"], draft["narrative"], draft["source"])
        st.markdown(report_md)
        st.download_button("Download draft report (.md)", report_md,
                           file_name=f"DRAFT_report_{sid}_{datetime.now(LOCAL):%Y%m%d_%H%M}.md")

        st.subheader("Revise the narrative")
        st.caption("Ask the local AI to reword the narrative. Dates, deadlines, and flags stay fixed; "
                   "requests to change dates, mark complete, sign, or declare compliance are refused.")
        for m in draft["chat"]:
            with st.chat_message(m["role"]):
                st.write(m["text"])
        ask = st.chat_input("e.g. Use plainer language; mention the crew was notified on site")
        if ask:
            draft["chat"].append({"role": "user", "text": ask})
            allowed, reason = validator.check_request(ask)
            if not allowed:
                draft["chat"].append({"role": "assistant", "text": reason})
            else:
                with st.spinner("Revising with the local AI..."):
                    text, source, problems = write_narrative(draft["facts"], draft["narrative"], ask)
                if source == "unchanged":
                    draft["chat"].append({"role": "assistant", "text": "Revision rejected, draft kept as it was: "
                                          + " ".join(problems)})
                else:
                    draft.update(narrative=text, source=source, problems=[])
                    draft["chat"].append({"role": "assistant", "text": "Narrative revised and validated."})
            st.rerun()

with verify:
    st.caption(f"Runs every case in tests/cases.json ({verifier.CASES_FILE.name}) against the Python rules, "
               "the validator, and the revise-chat guardrails. No AI or internet needed.")
    if st.button("Run test suite", type="primary"):
        st.session_state["results"] = verifier.run_all()
    res = st.session_state.get("results")
    if res:
        df = pd.DataFrame(res)
        cols = st.columns(4)
        cols[0].metric("All cases", f"{df['passed'].mean():.0%}", f"{df['passed'].sum()}/{len(df)} passed")
        for col, label in zip(cols[1:], ["typical", "hard", "adversarial"]):
            part = df[df["label"] == label]
            if len(part):
                col.metric(label.title(), f"{part['passed'].mean():.0%}", f"{part['passed'].sum()}/{len(part)}")
        df["Result"] = df["passed"].map({True: "PASS", False: "FAIL"})
        st.dataframe(df[["Result", "id", "label", "type", "rule", "description", "expected", "actual"]],
                     hide_index=True, width="stretch")
        failed = int((~df["passed"]).sum())
        if failed and st.button(f"Save {failed} failure(s) to data/failure_register.csv"):
            verifier.save_failures(res)
            st.success("Saved. Fill in the cause and fix columns.")
