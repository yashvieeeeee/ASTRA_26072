"""Ephemeral, forecaster-triggered Weatherbit lightning corroboration."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import os
import threading
import time

import requests
from .config import environment_value

WEATHERBIT_LIGHTNING_URL = "https://api.weatherbit.io/v2.0/current/lightning"


@dataclass(frozen=True)
class WeatherbitUnavailable(Exception):
    code: str
    message: str
    status_code: int


class WeatherbitLightningClient:
    """Live lookup only: results are transformed for the response then discarded.

    This object deliberately holds only rate-limit timestamps. It never caches
    provider responses, writes to disk, mutates the fused dataset, or touches
    the warning/audit database.
    """
    def __init__(self, api_key: str | None = None, *, clock=time.monotonic):
        self._api_key = api_key if api_key is not None else environment_value("ASTRA_WEATHERBIT_KEY")
        self._clock = clock
        self._requests: deque[float] = deque()
        self._lock = threading.Lock()

    def lookup(self, latitude: float, longitude: float) -> dict:
        if not self._api_key:
            raise WeatherbitUnavailable("NOT_CONFIGURED", "Live Weatherbit corroboration is not configured.", 503)
        if not 6 <= latitude <= 38 or not 68 <= longitude <= 98:
            raise WeatherbitUnavailable("OUTSIDE_DOMAIN", "Lightning corroboration is limited to the ASTRA pan-India domain.", 422)
        self._claim_request_slot()
        try:
            response = requests.get(WEATHERBIT_LIGHTNING_URL, params={
                "lat": latitude, "lon": longitude, "search_distance_km": 75,
                "search_mins": 15, "limit": 20, "sort": "distance", "output_type": "json",
                "key": self._api_key,
            }, timeout=15, headers={"Accept": "application/json"})
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            # Do not include URLs or provider payloads: either can expose the key.
            raise WeatherbitUnavailable("PROVIDER_UNAVAILABLE", "Weatherbit live corroboration is unavailable.", 502) from exc

        observations = [
            {key: strike.get(key) for key in ("id", "lat", "lon", "timestamp_utc", "type", "source")}
            for strike in payload.get("lightning", [])[:20]
        ]
        # ``payload`` goes out of scope immediately after this return. Only this
        # response body is displayed to the requesting forecaster.
        return {
            "provider": "weatherbit", "classification": "live_third_party_corroboration_not_model_input",
            "search_distance_km": 75, "search_mins": 15,
            "event_count": int(payload.get("count", len(observations))),
            "observations": observations,
        }

    def _claim_request_slot(self) -> None:
        now = self._clock()
        with self._lock:
            while self._requests and now - self._requests[0] >= 86_400:
                self._requests.popleft()
            if len(self._requests) >= 50:
                raise WeatherbitUnavailable("QUOTA_REACHED", "Live Weatherbit corroboration unavailable: daily quota reached.", 429)
            if self._requests and now - self._requests[-1] < 1:
                raise WeatherbitUnavailable("RATE_LIMITED", "Live Weatherbit corroboration unavailable: one request per second.", 429)
            self._requests.append(now)
