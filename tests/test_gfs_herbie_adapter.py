"""GFS/Herbie integration uses a fake reader; CI never downloads GRIB data."""
from types import SimpleNamespace
import sys

import numpy as np
import pytest
import xarray as xr

from astra_pipeline.adapters import NWPAdapter, nwp_realtime_provider
from astra_pipeline.domain import LATITUDES, LONGITUDES


def test_gfs_herbie_is_full_grid_default_and_normalises_requested_fields(monkeypatch, tmp_path):
    calls = []

    class FakeHerbie:
        def __init__(self, date, **kwargs):
            self.date = date
            self.fxx = kwargs["fxx"]
            calls.append(kwargs)

        def xarray(self, *, search, remove_grib):
            assert search == r":(?:CAPE:surface|(?:TMP|RH|UGRD|VGRD):(?:1000|500) mb:)"
            assert remove_grib is True
            latitude = np.array([6.0, 38.0])
            longitude = np.array([68.0, 98.0])
            cape = xr.Dataset({"cape": (("latitude", "longitude"), np.full((2, 2), 100 + self.fxx))},
                              coords={"latitude": latitude, "longitude": longitude})
            pressure = xr.Dataset(
                {name: (("isobaricInhPa", "latitude", "longitude"), np.full((2, 2, 2), value + self.fxx),
                 {"GRIB_shortName": name})
                 for name, value in {"t": 300, "r": 70, "u": 4, "v": 2}.items()},
                coords={"isobaricInhPa": [1000, 500], "latitude": latitude, "longitude": longitude},
            )
            pressure["u"].loc[{"isobaricInhPa": 500}] = 18 + self.fxx
            pressure["v"].loc[{"isobaricInhPa": 500}] = 8 + self.fxx
            return [cape, pressure]

    monkeypatch.setitem(sys.modules, "herbie", SimpleNamespace(Herbie=FakeHerbie))
    monkeypatch.delenv("ASTRA_NWP_REALTIME_PROVIDER", raising=False)
    monkeypatch.setenv("ASTRA_SATELLITE_CONFIG", str(tmp_path / "absent.json"))
    monkeypatch.setenv("ASTRA_GFS_FORECAST_HOURS", "2")
    monkeypatch.setenv("ASTRA_GFS_LOOKBACK_CYCLES", "1")
    monkeypatch.setenv("ASTRA_HERBIE_CACHE_DIR", str(tmp_path / "herbie"))

    dataset = NWPAdapter().load("realtime")

    assert nwp_realtime_provider() == "gfs_herbie"
    assert len(calls) == 2
    assert all(call["model"] == "gfs" and call["product"] == "pgrb2.0p25" for call in calls)
    assert dataset.attrs["provider"] == "gfs_herbie"
    assert dataset.attrs["mode"] == "realtime"
    assert dataset.sizes == {"time": 2, "latitude": len(LATITUDES), "longitude": len(LONGITUDES)}
    assert dataset.cape.sel(latitude=22, longitude=82).isel(time=1).item() == 101
    assert dataset.u_1000.sel(latitude=22, longitude=82).isel(time=0).item() == 4
    assert dataset.u_500.sel(latitude=22, longitude=82).isel(time=0).item() == 18
    assert np.isnan(dataset.cin).all()


def test_open_meteo_is_rejected_for_full_grid(monkeypatch):
    monkeypatch.setenv("ASTRA_NWP_REALTIME_PROVIDER", "open_meteo")
    with pytest.raises(RuntimeError, match="small point queries"):
        NWPAdapter().load("realtime")


def test_nwp_provider_rejects_unknown_value(monkeypatch):
    monkeypatch.setenv("ASTRA_NWP_REALTIME_PROVIDER", "unrecognised")
    with pytest.raises(ValueError, match="Unknown nwp_realtime_provider"):
        nwp_realtime_provider()
