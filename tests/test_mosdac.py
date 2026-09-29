from __future__ import annotations

import io
import json

import numpy as np
import pytest
import xarray as xr

from astra_pipeline.contracts import Mode
from astra_pipeline.domain import LATITUDES, LONGITUDES
from astra_pipeline.mosdac import MOSDACDownloader, MOSDACQuotaExceeded, MOSDACScene, MOSDACStager
from astra_pipeline.adapters import INSATAdapter, satellite_provider
from scripts.ingest_mosdac import ingest


class Response:
    def __init__(self, status_code=200, body=None, payload=b"hdf"):
        self.status_code, self._body, self._payload = status_code, body or {}, payload
    def json(self): return self._body
    def iter_content(self, chunk_size): yield self._payload


class Session:
    def __init__(self, *, download_status=200): self.download_status = download_status; self.calls = []
    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs)); return Response(body={"access_token": "not-a-real-token"})
    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        if "datasets" in url:
            return Response(body={"entries": [{"id": "record-1", "identifier": "3RIMG_20260101_0000_L1C_ASIA_MER.h5"}]})
        return Response(self.download_status, payload=b"fixture")


class Reader:
    def read(self, path):
        shape = (1, len(LATITUDES), len(LONGITUDES))
        return xr.Dataset({name: (("time", "latitude", "longitude"), np.full(shape, value), {"units": "K"})
                           for name, value in [("ir1_brightness_temperature", 280), ("tir1_brightness_temperature", 278), ("wv_brightness_temperature", 250)]},
                          coords={"time": [np.datetime64("2026-01-01T00:00")], "latitude": LATITUDES, "longitude": LONGITUDES})


class BrokenReader:
    def read(self, path): raise ValueError("invalid bytes")


def credentials_file(tmp_path):
    path = tmp_path / "mosdac-credentials.json"
    path.write_text(json.dumps({"username": "user", "password": "secret"}))
    return path


def test_normal_download_search_and_staging_are_fully_mocked(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ASTRA_MOSDAC_CONFIG", str(credentials_file(tmp_path)))
    session = Session(); downloader = MOSDACDownloader(tmp_path / "raw", session=session)
    scenes = downloader.find(np.datetime64("2026-01-01").astype(object), np.datetime64("2026-01-01").astype(object),
                             ["3RIMG_L1C_ASIA_MER"], count=3, bounding_box="68.0,6.0,98.0,38.0")
    assert len(scenes) == 1
    assert session.calls[-1][2]["params"] == {"datasetId": "3RIMG_L1C_ASIA_MER", "startTime": "2026-01-01", "endTime": "2026-01-01", "count": "3", "boundingBox": "68.0,6.0,98.0,38.0"}
    ingest(scenes, downloader, MOSDACStager(tmp_path / "staged", Reader(), mode=Mode.historical))
    staged = xr.open_zarr(tmp_path / "staged" / "historical.zarr")
    assert staged.attrs["provider"] == "mosdac" and staged.attrs["mode"] == "historical" and staged.attrs["is_synthetic"] is False
    assert "secret" not in capsys.readouterr().out


def test_missing_scene_is_reported_without_staging(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ASTRA_MOSDAC_CONFIG", str(credentials_file(tmp_path)))
    downloader = MOSDACDownloader(tmp_path / "raw", session=Session(download_status=404))
    scene = MOSDACScene("missing", "missing.h5", "3DIMG_L1C_SGP")
    ingest([scene], downloader, MOSDACStager(tmp_path / "staged", Reader()))
    assert "status=missing" in capsys.readouterr().out
    assert not list((tmp_path / "staged" / "frames").glob("*.nc"))


def test_corrupt_file_never_stages_partial_frame(tmp_path):
    raw = tmp_path / "bad.h5"; raw.write_bytes(b"broken")
    with pytest.raises(RuntimeError, match="corrupt"):
        MOSDACStager(tmp_path / "staged", BrokenReader()).stage(raw)
    assert not list((tmp_path / "staged" / "frames").glob("*.nc"))


def test_quota_stops_before_another_download_request(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRA_MOSDAC_CONFIG", str(credentials_file(tmp_path)))
    session = Session(); downloader = MOSDACDownloader(tmp_path / "raw", session=session, quota_limit=1)
    first = MOSDACScene("one", "one.h5", "3DIMG_L1C_SGP"); second = MOSDACScene("two", "two.h5", "3DIMG_L1C_SGP")
    assert downloader.download(first)
    with pytest.raises(MOSDACQuotaExceeded, match="stopping"):
        downloader.download(second)
    assert len([call for call in session.calls if call[0] == "get" and "download" in call[1]]) == 1


def test_bad_credentials_are_clear_and_never_echoed(tmp_path, monkeypatch):
    path = credentials_file(tmp_path); monkeypatch.setenv("ASTRA_MOSDAC_CONFIG", str(path))
    class BadSession(Session):
        def post(self, url, **kwargs): return Response(401, {"error": "bad credentials"})
    with pytest.raises(RuntimeError, match="authentication failed") as error:
        MOSDACDownloader(tmp_path / "raw", session=BadSession()).download(MOSDACScene("one", "one.h5", "3DIMG_L1C_SGP"))
    assert "secret" not in str(error.value)


def test_missing_credentials_fails_before_network(tmp_path, monkeypatch):
    monkeypatch.delenv("ASTRA_MOSDAC_CONFIG", raising=False)
    with pytest.raises(RuntimeError, match="ASTRA_MOSDAC_CONFIG"):
        MOSDACDownloader(tmp_path / "raw", session=Session()).login()


def test_mosdac_provider_requires_staged_non_secret_configuration(tmp_path, monkeypatch):
    config = tmp_path / "satellite.json"; config.write_text('{"satellite_provider": "mosdac"}')
    monkeypatch.setenv("ASTRA_SATELLITE_CONFIG", str(config))
    assert satellite_provider() == "mosdac"
    with pytest.raises(RuntimeError, match="not set up"):
        INSATAdapter().load("historical")
