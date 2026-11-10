"""Find the NOAA weather stations nearest to a site."""
import math

import requests

from config import MAX_STATION_MI, NWS_BASE, NWS_HEADERS


def distance_mi(lat1, lon1, lat2, lon2):
    """Straight-line distance between two points, in miles."""
    r = 3958.8  # Earth radius, miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearby_stations(lat, lon):
    """Ask the NWS API which stations serve this point. Closest first."""
    point = requests.get(f"{NWS_BASE}/points/{lat:.4f},{lon:.4f}",
                         headers=NWS_HEADERS, timeout=20)
    point.raise_for_status()
    stations_url = point.json()["properties"]["observationStations"]

    resp = requests.get(stations_url, headers=NWS_HEADERS, timeout=20)
    resp.raise_for_status()

    stations = []
    for feature in resp.json().get("features", []):
        props = feature["properties"]
        station_id = props["stationIdentifier"]
        # Airport (ASOS/AWOS) stations have 4-letter IDs such as KBZN.
        if len(station_id) != 4:
            continue
        s_lon, s_lat = feature["geometry"]["coordinates"][:2]
        stations.append({
            "station_id": station_id,
            "name": props.get("name", ""),
            "lat": s_lat,
            "lon": s_lon,
            "distance_mi": round(distance_mi(lat, lon, s_lat, s_lon), 1),
        })
    return sorted(stations, key=lambda s: s["distance_mi"])


def nearest_station(lat, lon):
    """Return (closest station, flags). Flags STATION_TOO_FAR beyond MAX_STATION_MI."""
    stations = nearby_stations(lat, lon)
    if not stations:
        return None, ["NO_STATION"]
    best = stations[0]
    flags = ["STATION_TOO_FAR"] if best["distance_mi"] > MAX_STATION_MI else []
    return best, flags