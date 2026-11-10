"""Construction Stormwater Inspection Agent - Streamlit dashboard."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

from agent.rainfall import load_cache, rain_for_station, storm_trigger
from agent.stations import nearest_station
from config import (LAST_REFRESH_FILE, MAX_STATION_MI, OLLAMA_HOST, OLLAMA_MODEL,
                    SITE_STATIONS_FILE, SITE_TZ, SITES_FILE, STORM_THRESHOLD_IN)

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


def local_time(ts):
    """UTC datetime -> readable local time, e.g. 'Mon Nov 9 2:00 PM'."""
    if ts is None:
        return ""
    return ts.astimezone(LOCAL).strftime("%a %b %d %I:%M %p").replace(" 0", " ")


def load_sites():
    """Active sites from data/sites.csv."""
    sites = pd.read_csv(SITES_FILE, dtype=str)
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
        except requests.RequestException as e:
            errors.append(f"{site['site_id']}: station lookup failed ({e.__class__.__name__})")
        progress.progress((i + 1) / (2 * len(sites)), text="Finding nearest stations...")

    stations = sorted({row["station_id"] for row in lookup if row["station_id"]})
    for j, station_id in enumerate(stations):
        try:
            rain_for_station(station_id)
        except requests.RequestException as e:
            errors.append(f"{station_id}: rainfall download failed ({e.__class__.__name__})")
        progress.progress(0.5 + (j + 1) / (2 * max(len(stations), 1)),
                          text=f"Downloading rainfall for {station_id}...")

    if lookup:
        SITE_STATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(lookup).to_csv(SITE_STATIONS_FILE, index=False)
    LAST_REFRESH_FILE.write_text(datetime.now(timezone.utc).isoformat())
    progress.empty()
    return errors


# ---------- Triage table (reads saved data only) ----------
def build_triage(sites, site_stations):
    now = datetime.now(timezone.utc)
    rows = []
    for _, site in sites.iterrows():
        sid = site["site_id"]
        if sid not in site_stations.index or not site_stations.loc[sid, "station_id"]:
            rows.append({"Priority": "CHECK DATA", "Site": sid, "Name": site["name"],
                         "Flags": "NO_STATION_DATA"})
            continue
        st_row = site_stations.loc[sid]
        hourly = [r for r in load_cache(st_row["station_id"])
                  if r["hour_end_utc"] > now - timedelta(days=7)]
        trigger, max_24h, flags = storm_trigger(hourly)
        if isinstance(st_row["station_flags"], str) and st_row["station_flags"]:
            flags = flags + st_row["station_flags"].split(";")
        if trigger:
            priority = "STORM INSPECTION"
        elif flags:
            priority = "CHECK DATA"
        else:
            priority = "Routine"
        rows.append({
            "Priority": priority,
            "Site": sid,
            "Name": site["name"],
            "Station": st_row["station_id"],
            "Distance (mi)": st_row["distance_mi"],
            "Max 24-h rain (in)": round(max_24h, 2),
            "0.25 in reached": local_time(trigger),
            "24-h window ends": local_time(trigger + timedelta(hours=24)) if trigger else "",
            "_sort": trigger or now + timedelta(days=365),
            "Flags": ", ".join(flags),
        })
    table = pd.DataFrame(rows)
    order = {"STORM INSPECTION": 0, "CHECK DATA": 1, "Routine": 2}
    table["_p"] = table["Priority"].map(order)
    sort_cols = ["_p", "_sort"] if "_sort" in table else ["_p"]
    return table.sort_values(sort_cols).drop(columns=["_p", "_sort"], errors="ignore")


def color_priority(value):
    colors = {"STORM INSPECTION": "background-color: #f8d7da",
              "CHECK DATA": "background-color: #fff3cd",
              "Routine": "background-color: #d1e7dd"}
    return colors.get(value, "")


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
    st.caption(f"Active sites: {len(sites)}  |  Max station distance: {MAX_STATION_MI} mi  |  "
               f"Storm threshold: {STORM_THRESHOLD_IN} in / 24 h  |  Times: {SITE_TZ}")

st.title("Construction Stormwater Inspection Agent")
st.caption("DRAFT tool. Inspector review required. The agent never completes, "
           "signs, or edits inspection records.")

triage, checklist, report, verify = st.tabs(
    ["Storm Triage", "Site Checklist", "Draft Report", "Verification"])

with triage:
    left, right = st.columns([1, 3])
    with left:
        if st.button("Refresh rainfall", type="primary", width="stretch"):
            errors = refresh_rainfall(sites)
            for err in errors:
                st.error(err)
            st.rerun()
    with right:
        st.caption("Rainfall comes from saved data. Only **Refresh rainfall** contacts NOAA "
                   "(last 7 days of hourly reports for each site's nearest station).")

    site_stations = load_site_stations()
    if site_stations.empty:
        st.info("No rainfall data yet. Click **Refresh rainfall**.")
    else:
        table = build_triage(sites, site_stations)
        st.dataframe(table.style.map(color_priority, subset=["Priority"]),
                     hide_index=True, width="stretch")
        st.caption("24-h window ends = time 0.25 in was reached + 24 h (CGP 4.2.2a). "
                   "Working-hour, weekend, and routine 7/14-day due dates are added "
                   "when scheduler.py is built.")

        map_sites = sites[["lat", "lon"]].assign(color="#1f6f8b", size=60)
        stations = site_stations.dropna(subset=["station_lat"])
        map_stations = pd.DataFrame({"lat": stations["station_lat"], "lon": stations["station_lon"],
                                     "color": "#d9534f", "size": 90})
        st.subheader("Sites (blue) and weather stations (red)")
        st.map(pd.concat([map_sites, map_stations]), latitude="lat", longitude="lon",
               color="color", size="size")

with checklist:
    st.info("Phase 4: site-specific checklist with SWPPP citations.")
with report:
    st.info("Phase 4: draft report and corrective-action deadlines.")
with verify:
    st.info("Phase 5: synthetic rainfall scenarios, pass/fail.")