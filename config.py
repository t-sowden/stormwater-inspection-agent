"""Project settings. Change values here, not inside the other files."""
from pathlib import Path

# Use Windows' own certificates for web requests (same fix as UV_SYSTEM_CERTS).
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

# Folders
ROOT = Path(__file__).parent
DATA = ROOT / "data"
RAIN_CACHE = DATA / "rain_cache"
SITES_FILE = DATA / "sites.csv"
SITE_STATIONS_FILE = RAIN_CACHE / "site_stations.csv"
LAST_REFRESH_FILE = RAIN_CACHE / "last_refresh.txt"
# Local AI
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2:3b"
# Time zone used to display times (sites' local time)
SITE_TZ = "America/Denver"
# Permit and team rules
STORM_THRESHOLD_IN = 0.25      # CGP: 0.25 in within 24 hours
MAX_STATION_MI = 10.0          # team decision Nov 8: max representative distance
DATA_LATE_HOURS = 2            # newest report older than this = DATA_LATE

# NOAA / National Weather Service API (free, no key)
NWS_BASE = "https://api.weather.gov"
NWS_CONTACT = "thomas.sowden@colostate.edu"   # <-- put a contact email here
NWS_HEADERS = {
    "User-Agent": f"(stormwater-agent, {NWS_CONTACT})",
    "Accept": "application/geo+json",
}