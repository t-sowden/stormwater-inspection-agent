import requests
import streamlit as st

from config import MAX_STATION_MI, OLLAMA_HOST, OLLAMA_MODEL

st.set_page_config(page_title="Stormwater Inspection Agent", layout="wide")


def ollama_status():
    """Return (connected, list of model names) for the local Ollama server."""
    try:
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
        r.raise_for_status()
        return True, [m["name"] for m in r.json().get("models", [])]
    except requests.RequestException:
        return False, []


connected, models = ollama_status()

with st.sidebar:
    st.header("System status")
    if not connected:
        st.error("Ollama not reachable at localhost:11434. Start the Ollama app.")
    elif not any(m.startswith(OLLAMA_MODEL) for m in models):
        st.warning(f"Model missing. Run: ollama pull {OLLAMA_MODEL}")
    else:
        st.success(f"Ollama connected: {OLLAMA_MODEL}")
    st.caption(f"Max representative station distance: {MAX_STATION_MI} mi")

st.title("Construction Stormwater Inspection Agent")
st.caption("DRAFT tool. Inspector review required. The agent never completes, "
           "signs, or edits inspection records.")

triage, checklist, report, verify = st.tabs(
    ["Storm Triage", "Site Checklist", "Draft Report", "Verification"])
with triage:
    st.info("Phase 3: rainfall, station distance, and inspection due dates per site.")
with checklist:
    st.info("Phase 4: site-specific checklist with SWPPP citations.")
with report:
    st.info("Phase 4: draft report and corrective-action deadlines.")
with verify:
    st.info("Phase 6: synthetic rainfall scenarios, pass/fail.")