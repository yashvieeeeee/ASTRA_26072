"""WeatherAPI weather corroboration remains live, labelled, and non-model input."""
from fastapi.testclient import TestClient

from astra_api.app import create_app


def test_weatherapi_current_returns_normalized_live_observation(monkeypatch, tmp_path):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {
            "location": {"name": "Mumbai", "region": "Maharashtra", "country": "India", "lat": 19.08, "lon": 72.88},
            "current": {"last_updated": "2026-09-29 12:00", "temp_c": 29.2, "feelslike_c": 34.1, "humidity": 76,
                "wind_kph": 12.0, "wind_degree": 250, "pressure_mb": 1008, "precip_mm": 0.1, "cloud": 75,
                "condition": {"text": "Partly cloudy"}},
        }
    monkeypatch.setenv("ASTRA_WEATHERAPI_KEY", "test-key")
    monkeypatch.setattr("astra_api.weatherapi.requests.get", lambda *args, **kwargs: Response())
    response = TestClient(create_app(audit_database=str(tmp_path / "audit.db"))).get("/api/v1/weather/corroboration?latitude=19.076&longitude=72.878")
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "weatherapi"
    assert body["classification"] == "live_third_party_corroboration_not_model_input"
    assert body["is_synthetic"] is False
    assert body["conditions"]["temperature_c"] == 29.2


def test_weatherapi_requires_configuration(monkeypatch, tmp_path):
    monkeypatch.delenv("ASTRA_WEATHERAPI_KEY", raising=False)
    monkeypatch.setattr("astra_api.weatherapi.environment_value", lambda _: None)
    response = TestClient(create_app(audit_database=str(tmp_path / "audit.db"))).get("/api/v1/weather/corroboration?latitude=19&longitude=73")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "NOT_CONFIGURED"
