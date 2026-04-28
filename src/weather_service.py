"""
Real-time weather enrichment via OpenWeatherMap API.

Fetches current weather conditions along the delivery route (at pickup and
drop-off points) and returns structured features for the model.

Env var:
  OPENWEATHER_API_KEY — if not set, returns None (model uses the dispatcher-entered value).
"""

import os
import logging
from typing import Optional

import requests

logger = logging.getLogger("shipment_delay")

API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
BASE_URL = "https://api.openweathermap.org/data/2.5/weather"

WEATHER_ID_MAP = {
    range(200, 300): "Stormy",
    range(300, 400): "Cloudy",
    range(500, 600): "Stormy",
    range(600, 700): "Stormy",
    range(700, 762): "Fog",
    range(762, 800): "Sandstorms",
    range(800, 801): "Sunny",
    range(801, 900): "Cloudy",
}


def _map_weather_id(weather_id: int) -> str:
    for id_range, label in WEATHER_ID_MAP.items():
        if weather_id in id_range:
            return label
    return "Sunny"


def _fetch_weather(lat: float, lon: float) -> Optional[dict]:
    if not API_KEY:
        return None
    try:
        resp = requests.get(
            BASE_URL,
            params={"lat": lat, "lon": lon, "appid": API_KEY, "units": "metric"},
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("Weather API call failed for (%.4f, %.4f): %s", lat, lon, e)
        return None


def get_route_weather(
    store_lat: float, store_lon: float,
    drop_lat: float, drop_lon: float,
) -> Optional[dict]:
    if not API_KEY:
        logger.debug("OPENWEATHER_API_KEY not set — skipping live weather")
        return None

    pickup = _fetch_weather(store_lat, store_lon)
    dropoff = _fetch_weather(drop_lat, drop_lon)

    if not pickup and not dropoff:
        return None

    pickup_data = pickup or dropoff
    dropoff_data = dropoff or pickup

    pickup_id = pickup_data["weather"][0]["id"]
    dropoff_id = dropoff_data["weather"][0]["id"]
    worst_id = max(pickup_id, dropoff_id)

    result = {
        "weather_label": _map_weather_id(worst_id),
        "pickup_temp_c": pickup_data["main"]["temp"],
        "dropoff_temp_c": dropoff_data["main"]["temp"],
        "pickup_wind_speed": pickup_data["wind"]["speed"],
        "dropoff_wind_speed": dropoff_data["wind"]["speed"],
        "pickup_humidity": pickup_data["main"]["humidity"],
        "dropoff_humidity": dropoff_data["main"]["humidity"],
        "pickup_visibility_m": pickup_data.get("visibility", 10000),
        "dropoff_visibility_m": dropoff_data.get("visibility", 10000),
        "pickup_weather_id": pickup_id,
        "dropoff_weather_id": dropoff_id,
    }

    logger.info(
        "Live weather: pickup=%s (id=%d) dropoff=%s (id=%d) -> label=%s",
        pickup_data["weather"][0]["description"], pickup_id,
        dropoff_data["weather"][0]["description"], dropoff_id,
        result["weather_label"],
    )
    return result
