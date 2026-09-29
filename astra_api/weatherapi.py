"""Ephemeral WeatherAPI current-conditions corroboration."""
from __future__ import annotations

import os

import requests
from .config import environment_value

WEATHERAPI_CURRENT_URL = "https://api.weatherapi.com/v1/current.json"


class WeatherAPIUnavailable(Exception):
    def __init__(self, code: str, message: str, status_code: int):
        self.code, self.message, self.status_code = code, message, status_code


class WeatherAPIClient:
    """Fetch a live point observation without affecting nowcast model inputs."""
    def __init__(self, api_key: str | None = None):
        self._api_key = api_key if api_key is not None else environment_value("ASTRA_WEATHERAPI_KEY")

    def current(self, latitude: float, longitude: float) -> dict:
        if not self._api_key:
            raise WeatherAPIUnavailable("NOT_CONFIGURED", "Live WeatherAPI conditions are not configured.", 503)
        if not 6 <= latitude <= 38 or not 68 <= longitude <= 98:
            raise WeatherAPIUnavailable("OUTSIDE_DOMAIN", "WeatherAPI corroboration is limited to the ASTRA pan-India domain.", 422)
        try:
            response = requests.get(
                WEATHERAPI_CURRENT_URL,
                params={"key": self._api_key, "q": f"{latitude},{longitude}", "aqi": "no"},
                timeout=15,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            # The URL includes the secret key, so never expose provider details.
            raise WeatherAPIUnavailable("PROVIDER_UNAVAILABLE", "WeatherAPI live conditions are unavailable.", 502) from exc

        current, location = payload.get("current", {}), payload.get("location", {})
        return {
            "provider": "weatherapi",
            "classification": "live_third_party_corroboration_not_model_input",
            "is_synthetic": False,
            "observed_at": current.get("last_updated") or location.get("localtime"),
            "location": {key: location.get(key) for key in ("name", "region", "country", "lat", "lon")},
            "conditions": {
                "temperature_c": current.get("temp_c"),
                "feelslike_c": current.get("feelslike_c"),
                "humidity_pct": current.get("humidity"),
                "wind_kph": current.get("wind_kph"),
                "wind_degree": current.get("wind_degree"),
                "pressure_mb": current.get("pressure_mb"),
                "precipitation_mm": current.get("precip_mm"),
                "cloud_pct": current.get("cloud"),
                "condition": (current.get("condition") or {}).get("text"),
            },
        }
