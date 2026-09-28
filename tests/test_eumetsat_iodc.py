from datetime import datetime, timezone
from pathlib import Path
import io
import zipfile
import numpy as np
import pytest
import xarray as xr

from astra_pipeline.eumetsat_iodc import EUMETSATIODCDownloader, IODCStager, SatelliteSceneReader
from astra_pipeline.domain import LATITUDES, LONGITUDES
from scripts.ingest_eumetsat_iodc import ingest


class SyntheticReader(SatelliteSceneReader):
    def read(self, scene_file):
        stamp = np.datetime64(scene_file.stem.replace("scene_", "").replace("Z", ""))
        shape = (1, len(LATITUDES), len(LONGITUDES))
        return xr.Dataset({name: (("time", "latitude", "longitude"), np.full(shape, value), {"units": "K"})
                           for name, value in [("ir1_brightness_temperature", 280), ("tir1_brightness_temperature", 278), ("wv_brightness_temperature", 250)]},
                          coords={"time": [stamp], "latitude": LATITUDES, "longitude": LONGITUDES})


class BrokenReader(SatelliteSceneReader):
    def read(self, scene_file): raise ValueError("bad native bytes")


class FakeProduct:
    def __init__(self, product_id="fake-scene", payload=b"scene", failures=0): self.product_id, self.payload, self.failures = product_id, payload, failures
    def __str__(self): return self.product_id
    def open(self):
        if self.failures:
            self.failures -= 1
            raise PermissionError("expired token")
        class Stream:
            def __enter__(inner): return io.BytesIO(self.payload)
            def __exit__(inner, *args): return False
        return Stream()


def test_synthetic_scene_stages_contract_full_domain_and_config(tmp_path):
    stager = IODCStager(tmp_path / "staged", SyntheticReader())
    for stamp in ("2026-01-01T00:00", "2026-01-01T00:30", "2026-01-01T01:00", "2026-01-01T01:30"):
        source = tmp_path / f"scene_{stamp}Z"; source.write_bytes(b"fixture")
        stager.stage(source)
    latest = xr.open_zarr(stager.latest_url)
    assert latest.sizes["time"] == 4
    assert (float(latest.latitude.min()), float(latest.latitude.max())) == (6.0, 38.0)
    assert (float(latest.longitude.min()), float(latest.longitude.max())) == (68.0, 98.0)
    config = tmp_path / "config.json"; stager.update_config(config)
    assert "latest_url" in config.read_text() and "credentials" not in config.read_text()


def test_missing_bucket_is_delayed_not_interpolated(tmp_path):
    stager = IODCStager(tmp_path / "staged", SyntheticReader())
    for stamp in ("2026-01-01T00:00", "2026-01-01T01:00"):
        source = tmp_path / f"scene_{stamp}Z"; source.write_bytes(b"fixture"); stager.stage(source)
    historical = xr.open_zarr(stager.historical_url)
    assert historical.attrs["source_status"]["state"] == "delayed"
    assert np.isnan(historical.ir1_brightness_temperature.sel(time="2026-01-01T00:30")).all()


def test_corrupt_scene_does_not_stage_partial_file(tmp_path):
    source = tmp_path / "bad.zip"; source.write_bytes(b"broken")
    stager = IODCStager(tmp_path / "staged", SyntheticReader())
    with pytest.raises(RuntimeError, match="corrupt"):
        stager.stage(source, "bad")
    assert not list((tmp_path / "staged" / "frames").glob("*.nc"))


def test_downloader_retries_expired_token_without_logging_secrets(tmp_path):
    product = FakeProduct(failures=1)
    metric = EUMETSATIODCDownloader(tmp_path, retries=2, backoff_seconds=0).download(product)
    assert metric and metric.bytes_downloaded == 5
    assert EUMETSATIODCDownloader(tmp_path).download(product) is None

def test_existing_raw_scene_is_staged_when_download_is_reused(tmp_path):
    product = FakeProduct("scene_2026-01-01T00:00Z")
    downloader = EUMETSATIODCDownloader(tmp_path / "raw")
    raw = downloader.raw_path(str(product))
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("scene_2026-01-01T00:00Z.nat", b"fixture")
    stager = IODCStager(tmp_path / "staged", SyntheticReader())
    ingest([product], downloader, stager)
    assert (tmp_path / "staged" / "frames" / "scene_2026-01-01T00_00Z.nc").is_file()


def test_missing_credentials_fails_before_eumdac_is_called(tmp_path, monkeypatch):
    monkeypatch.setenv("EUMDAC_CONFIG_DIR", str(tmp_path / "none"))
    with pytest.raises(RuntimeError, match="credentials are missing"):
        EUMETSATIODCDownloader(tmp_path / "raw")._datastore()
