from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"

OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2:3b"

STORM_THRESHOLD_IN = 0.25      # CGP 0.25 in within 24 hours
MAX_STATION_MI = 10.0          # team decision: max representative distance

MESONET_BASE = "https://mesonet.climate.umt.edu/api/v2"
NCEI_BASE = "https://www.ncei.noaa.gov/access/services/data/v1"