"""Meteostat integration tests use a fake client; pytest must not hit its API."""
from datetime import datetime
from types import SimpleNamespace
import sys

import numpy as np
import pytest

from astra_pipeline.adapters import GroundStationAdapter


def test_meteostat_observations_are_converted_and_remote_cells_stay_missing(monkeypatch):
    pd = pytest.importorskip("pandas")

    class FakeStations:
        def nearby(self, latitude, longitude): return self
        def fetch(self, limit):
            return pd.DataFrame({"latitude": [19.076], "longitude": [72.878]}, index=["TEST"])

    class FakeHourly:
        def __init__(self, station, start, end): pass
        def fetch(self):
            return pd.DataFrame({"temp": [25.0, 26.0], "rhum": [80., 81.], "pres": [1000., 1001.],
                                 "wspd": [36., 18.], "prcp": [2., 0.]},
                                index=pd.to_datetime(["2026-01-01T00:00", "2026-01-01T01:00"]))

    monkeypatch.setitem(sys.modules, "meteostat", SimpleNamespace(Stations=FakeStations, Hourly=FakeHourly))
    monkeypatch.setenv("ASTRA_METEOSTAT_START", "2026-01-01T00:00:00Z")
    monkeypatch.setenv("ASTRA_METEOSTAT_END", "2026-01-01T01:00:00Z")
    monkeypatch.setenv("ASTRA_METEOSTAT_ANCHOR_STEP_DEGREES", "100")
    monkeypatch.setenv("ASTRA_METEOSTAT_MAX_DISTANCE_KM", "75")

    dataset = GroundStationAdapter().load("historical")
    assert dataset.attrs["provider"] == "meteostat" and dataset.attrs["is_synthetic"] is False
    assert dataset.temperature_2m.sel(latitude=19., longitude=73.).isel(time=0).item() == pytest.approx(298.15)
    assert dataset.surface_pressure.sel(latitude=19., longitude=73.).isel(time=0).item() == pytest.approx(100000.)
    assert dataset.wind_speed_10m.sel(latitude=19., longitude=73.).isel(time=0).item() == pytest.approx(10.)
    assert dataset.station_available.sel(latitude=19., longitude=73.).isel(time=0).item() == 1
    assert np.isnan(dataset.temperature_2m.sel(latitude=38., longitude=98.).isel(time=0).item())
    assert dataset.station_available.sel(latitude=38., longitude=98.).isel(time=0).item() == 0
