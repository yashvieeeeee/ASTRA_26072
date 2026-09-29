"""Weatherbit corroboration is click-scoped, rate-limited, and non-persistent."""
from fastapi.testclient import TestClient

from astra_api.app import create_app
from astra_api.weatherbit import WeatherbitLightningClient, WeatherbitUnavailable


def test_weatherbit_lookup_returns_ephemeral_display_payload(monkeypatch, tmp_path):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"count": 1, "lightning": [{"id": 8, "lat": 19.1, "lon": 72.9,
            "timestamp_utc": "2026-09-29T00:00:00", "type": "flash", "source": "radar", "ignored": "never returned"}]}

    calls = []
    def fake_get(url, *, params, timeout, headers):
        calls.append((url, params, timeout, headers))
        return Response()

    monkeypatch.setenv("ASTRA_WEATHERBIT_KEY", "ci-configured-key")
    monkeypatch.setattr("astra_api.weatherbit.requests.get", fake_get)
    app = create_app(audit_database=str(tmp_path / "audit.db"))
    response = TestClient(app).get("/api/v1/lightning/corroboration?latitude=19.076&longitude=72.878")

    assert response.status_code == 200
    assert response.json() == {"provider": "weatherbit", "classification": "live_third_party_corroboration_not_model_input",
        "search_distance_km": 75, "search_mins": 15, "event_count": 1,
        "observations": [{"id": 8, "lat": 19.1, "lon": 72.9, "timestamp_utc": "2026-09-29T00:00:00", "type": "flash", "source": "radar"}]}
    assert calls[0][1]["search_distance_km"] == 75 and calls[0][1]["search_mins"] == 15
    assert "ignored" not in response.text and "ci-configured-key" not in response.text


def test_weatherbit_requires_key_and_enforces_daily_and_velocity_limits(monkeypatch, tmp_path):
    monkeypatch.delenv("ASTRA_WEATHERBIT_KEY", raising=False)
    monkeypatch.setattr("astra_api.weatherbit.environment_value", lambda _: None)
    response = TestClient(create_app(audit_database=str(tmp_path / "audit.db"))).get("/api/v1/lightning/corroboration?latitude=19&longitude=73")
    assert response.status_code == 503 and response.json()["detail"]["code"] == "NOT_CONFIGURED"

    clock = [0.0]
    client = WeatherbitLightningClient(api_key="configured-for-test", clock=lambda: clock[0])
    client._claim_request_slot()
    try:
        client._claim_request_slot()
    except WeatherbitUnavailable as exc:
        assert exc.code == "RATE_LIMITED" and exc.status_code == 429
    else:
        raise AssertionError("A second request in the same second must be rejected")

    clock[0] = 0
    daily = WeatherbitLightningClient(api_key="configured-for-test", clock=lambda: clock[0])
    for _ in range(50):
        daily._claim_request_slot()
        clock[0] += 1.1
    try:
        daily._claim_request_slot()
    except WeatherbitUnavailable as exc:
        assert exc.code == "QUOTA_REACHED" and exc.status_code == 429
    else:
        raise AssertionError("The 51st request in 24 hours must be rejected")
