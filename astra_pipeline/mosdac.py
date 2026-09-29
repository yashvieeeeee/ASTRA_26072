"""MOSDAC INSAT-3DR L1C ASIA_MER ingestion.

The MOSDAC API is intentionally kept behind a small client so tests never make
network calls.  Credentials are read only from ``ASTRA_MOSDAC_CONFIG``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import time
import tracemalloc
from typing import Iterable

import numpy as np
import xarray as xr

from .adapters import SATELLITE_CONTRACT
from .contracts import Mode, SourceMetadata
from .domain import LATITUDES, LONGITUDES, assert_pan_india
from .eumetsat_iodc import DownloadMetric

TOKEN_URL = "https://mosdac.gov.in/download_api/gettoken"
SEARCH_URL = "https://mosdac.gov.in/apios/datasets.json"
DOWNLOAD_URL = "https://mosdac.gov.in/download_api/download"
# Confirmed MOSDAC product: map-projected INSAT-3DR L1C Asia-Mercator scenes.
DATASET_IDS = ("3RIMG_L1C_ASIA_MER",)
DEFAULT_BOUNDING_BOX = "68.0,6.0,98.0,38.0"
DAILY_FILE_LIMIT = 5_000
CHANNELS = {"TIR1": "ir1_brightness_temperature", "TIR2": "tir1_brightness_temperature", "WV": "wv_brightness_temperature"}


class MOSDACQuotaExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class MOSDACScene:
    record_id: str
    identifier: str
    dataset_id: str


def _metadata(mode: Mode) -> SourceMetadata:
    return SourceMetadata(source=SATELLITE_CONTRACT.name, mode=mode, is_synthetic=False,
                          spatial_representation="grid", variables=list(SATELLITE_CONTRACT.required_variables),
                          units=SATELLITE_CONTRACT.required_variables)


class MOSDACDownloader:
    """MOSDAC documented token/search/download API with a persistent quota ledger.

    A file-download request consumes a quota slot before it is issued.  There is
    intentionally no automatic retry of download requests.
    """
    def __init__(self, raw_directory: str | Path, *, session=None, quota_limit: int = DAILY_FILE_LIMIT):
        self.raw_directory = Path(raw_directory); self.raw_directory.mkdir(parents=True, exist_ok=True)
        self.session = session
        self.quota_limit = quota_limit
        self._token: str | None = None
        self._ledger_path = self.raw_directory / ".mosdac-download-quota.json"

    @staticmethod
    def credentials() -> tuple[str, str]:
        configured = os.getenv("ASTRA_MOSDAC_CONFIG")
        if not configured:
            raise RuntimeError("MOSDAC credentials are missing: set ASTRA_MOSDAC_CONFIG to an external credentials JSON file.")
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise RuntimeError("MOSDAC credentials are missing: ASTRA_MOSDAC_CONFIG does not name a readable file.")
        # Refuse the repository configuration and only accept a credentials file.
        try:
            path.relative_to(Path.cwd().resolve())
        except ValueError:
            pass
        else:
            raise RuntimeError("MOSDAC credentials file must be outside the repository.")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            section = payload.get("user_credentials", payload)
            username = section.get("username") or section.get("username/email")
            password = section.get("password")
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            raise RuntimeError("MOSDAC credentials file is invalid; expected username and password JSON fields.") from exc
        if not isinstance(username, str) or not username or not isinstance(password, str) or not password:
            raise RuntimeError("MOSDAC credentials file is invalid; username and password are required.")
        return username, password

    def _requests(self):
        if self.session is not None:
            return self.session
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError("requests is required for MOSDAC ingestion. Install production dependencies.") from exc
        return requests

    def login(self) -> None:
        username, password = self.credentials()
        response = self._requests().post(TOKEN_URL, json={"username": username, "password": password}, timeout=30)
        if response.status_code in (400, 401):
            raise RuntimeError("MOSDAC authentication failed; verify the credentials in ASTRA_MOSDAC_CONFIG.")
        if response.status_code != 200:
            raise RuntimeError(f"MOSDAC authentication failed (HTTP {response.status_code}).")
        token = response.json().get("access_token")
        if not token:
            raise RuntimeError("MOSDAC authentication failed: no access token returned.")
        self._token = token

    def _ledger(self) -> dict:
        today = date.today().isoformat()
        try:
            ledger = json.loads(self._ledger_path.read_text())
        except (OSError, json.JSONDecodeError):
            ledger = {}
        return ledger if ledger.get("date") == today else {"date": today, "requests": 0}

    def _consume_download_request(self) -> None:
        ledger = self._ledger()
        if ledger["requests"] >= self.quota_limit:
            raise MOSDACQuotaExceeded(f"MOSDAC daily file quota reached ({self.quota_limit} download requests today); stopping without another request.")
        ledger["requests"] += 1
        self._ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    def find(self, start: datetime, end: datetime, dataset_ids: Iterable[str] = DATASET_IDS,
             *, count: int | None = None, bounding_box: str | None = DEFAULT_BOUNDING_BOX) -> list[MOSDACScene]:
        if count is not None and count < 1:
            raise ValueError("MOSDAC search count must be positive")
        client = self._requests(); scenes: list[MOSDACScene] = []
        for dataset_id in dataset_ids:
            params = {"datasetId": dataset_id, "startTime": start.strftime("%Y-%m-%d"), "endTime": end.strftime("%Y-%m-%d")}
            if count is not None: params["count"] = str(count)
            if bounding_box: params["boundingBox"] = bounding_box
            response = client.get(SEARCH_URL, params=params, timeout=30)
            if response.status_code != 200:
                raise RuntimeError(f"MOSDAC scene search failed for {dataset_id} (HTTP {response.status_code}).")
            body = response.json()
            # MOSDAC's documented client returns page records under ``entries``.
            # Retain the other shapes for compatibility with API revisions.
            records = body.get("entries") or body.get("data") or body.get("results") or body.get("records") or []
            for record in records:
                record_id = record.get("id") or record.get("_id") or record.get("recordId")
                identifier = record.get("identifier") or record.get("fileName") or record.get("name")
                if record_id and identifier:
                    scenes.append(MOSDACScene(str(record_id), str(identifier), dataset_id))
        return scenes

    def raw_path(self, scene: MOSDACScene) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", scene.identifier)
        return self.raw_directory / safe

    def download(self, scene: MOSDACScene) -> DownloadMetric | None:
        destination = self.raw_path(scene)
        if destination.is_file() and destination.stat().st_size:
            return None
        if self._token is None:
            self.login()
        self._consume_download_request()
        temporary = destination.with_suffix(destination.suffix + ".part")
        started = time.perf_counter()
        try:
            response = self._requests().get(DOWNLOAD_URL, headers={"Authorization": f"Bearer {self._token}"}, params={"id": scene.record_id}, stream=True, timeout=60)
            if response.status_code == 404:
                return None  # A search result can be withdrawn before download.
            if response.status_code == 429:
                raise MOSDACQuotaExceeded("MOSDAC rejected the download due to its rate/quota limit; stopping without retrying.")
            if response.status_code in (400, 401):
                raise RuntimeError("MOSDAC download was not authorised; verify credentials and access approval.")
            if response.status_code != 200:
                raise RuntimeError(f"MOSDAC download failed for scene {scene.identifier} (HTTP {response.status_code}); not retrying to preserve quota.")
            with temporary.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk: output.write(chunk)
            temporary.replace(destination)
            return DownloadMetric(scene.identifier, destination.stat().st_size, time.perf_counter() - started)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise


class HDF5INSATReader:
    """Read L1C ASIA_MER HDF5, calibrate IR counts through its BT LUT, and grid ASTRA's AOI."""
    def read(self, scene_file: Path) -> xr.Dataset:
        try:
            import h5py
            from scipy.interpolate import RegularGridInterpolator, griddata
        except ImportError as exc:
            raise RuntimeError("h5py and scipy are required for MOSDAC L1C decoding.") from exc
        try:
            with h5py.File(scene_file, "r") as h5:
                datasets = {name: obj[()] for name, obj in self._walk(h5) if getattr(obj, "ndim", 0) >= 1}
                projection = {key: value for key, value in h5["Projection_Information"].attrs.items()} if "Projection_Information" in h5 else None
            lat = self._pick(datasets, ("latitude", "lat")); lon = self._pick(datasets, ("longitude", "lon"))
            output = {}
            for channel, target in CHANNELS.items():
                values = self._pick(datasets, (channel,))
                if values is None: raise ValueError(f"L1C file has no {channel} channel")
                kelvin = self._brightness_temperature(np.asarray(values), self._pick_lut(datasets, channel))
                if lat is not None and lon is not None:
                    points = np.column_stack((np.asarray(lat).ravel(), np.asarray(lon).ravel()))
                    valid = np.isfinite(points).all(axis=1) & np.isfinite(kelvin.ravel())
                    target_lat, target_lon = np.meshgrid(LATITUDES, LONGITUDES, indexing="ij")
                    grid = griddata(points[valid], kelvin.ravel()[valid], (target_lat, target_lon), method="nearest")
                else:
                    grid = self._resample_mercator(datasets, projection, kelvin, RegularGridInterpolator)
                output[target] = (("time", "latitude", "longitude"), grid[np.newaxis].astype(np.float32), {"units": "K"})
        except Exception as exc:
            raise ValueError(f"invalid MOSDAC L1C HDF5 ({type(exc).__name__})") from exc
        stamp = self._timestamp(scene_file)
        result = xr.Dataset(output, coords={"time": [stamp], "latitude": LATITUDES, "longitude": LONGITUDES},
                            attrs={"provider": "mosdac", "satellite_provider": "mosdac", "product": "3RIMG_L1C_ASIA_MER"})
        SATELLITE_CONTRACT.validate(result, _metadata(Mode.historical)); assert_pan_india(result)
        return result

    @staticmethod
    def _walk(group, prefix=""):
        for key, value in group.items():
            name = f"{prefix}/{key}".lower()
            if hasattr(value, "items"): yield from HDF5INSATReader._walk(value, name)
            else: yield name, value

    @staticmethod
    def _pick(datasets, terms):
        matches = [(name, value) for name, value in datasets.items() if all(term.lower() in name for term in terms)]
        matches = [(name, value) for name, value in matches if "lut" not in name and "calib" not in name and "table" not in name]
        return min(matches, key=lambda item: len(item[0]))[1] if matches else None

    @staticmethod
    def _pick_lut(datasets, channel):
        matches = [(name, value) for name, value in datasets.items() if channel.lower() in name and any(token in name for token in ("lut", "bright", "temp", "calib"))]
        return min(matches, key=lambda item: len(item[0]))[1] if matches else None

    @staticmethod
    def _brightness_temperature(values, lut):
        values = values.astype(float)
        if np.nanmedian(values) > 100 and np.nanmedian(values) < 400: return values
        if lut is None: raise ValueError("channel counts have no brightness-temperature LUT")
        lut = np.asarray(lut, dtype=float).squeeze()
        if lut.ndim != 1: raise ValueError("brightness-temperature LUT is not one-dimensional")
        indexes = values.astype(int); result = np.full(values.shape, np.nan)
        valid = (indexes >= 0) & (indexes < lut.size)
        result[valid] = lut[indexes[valid]]
        return result

    @staticmethod
    def _resample_mercator(datasets, projection, values, interpolator_class):
        """Resample ASIA_MER's regular Mercator X/Y grid without 2-D geolocation."""
        x = next((value for name, value in datasets.items() if name.rsplit("/", 1)[-1] == "x"), None)
        y = next((value for name, value in datasets.items() if name.rsplit("/", 1)[-1] == "y"), None)
        if x is None or y is None or projection is None:
            raise ValueError("L1C file has neither latitude/longitude arrays nor Mercator X/Y metadata")
        try:
            from pyproj import CRS, Transformer
        except ImportError as exc:
            raise RuntimeError("pyproj is required for MOSDAC ASIA_MER map projection decoding.") from exc
        number = lambda key: float(np.asarray(projection[key]).reshape(-1)[0])
        source = CRS.from_proj4(
            f"+proj=merc +lat_ts={number('standard_parallel')} +lon_0={number('longitude_of_projection_origin')} "
            f"+a={number('semi_major_axis')} +b={number('semi_minor_axis')} +units=m +no_defs"
        )
        transformer = Transformer.from_crs("EPSG:4326", source, always_xy=True)
        target_lat, target_lon = np.meshgrid(LATITUDES, LONGITUDES, indexing="ij")
        target_x, target_y = transformer.transform(target_lon, target_lat)
        pixels = np.asarray(values, dtype=float).squeeze()
        if pixels.shape != (len(y), len(x)):
            raise ValueError(f"channel grid shape {pixels.shape} does not match X/Y coordinates {(len(y), len(x))}")
        x, y = np.asarray(x), np.asarray(y)
        if x[0] > x[-1]: x, pixels = x[::-1], pixels[:, ::-1]
        if y[0] > y[-1]: y, pixels = y[::-1], pixels[::-1, :]
        return interpolator_class((y, x), pixels, method="nearest", bounds_error=False, fill_value=np.nan)(
            np.column_stack((target_y.ravel(), target_x.ravel()))
        ).reshape(target_lat.shape)

    @staticmethod
    def _timestamp(scene_file: Path) -> np.datetime64:
        match = re.search(r"(20\d{6})[_T]?(\d{4,6})", scene_file.name)
        if match:
            return np.datetime64(datetime.strptime(match.group(1) + match.group(2)[:4], "%Y%m%d%H%M"), "ns")
        # MOSDAC's INSAT L1C filenames use DDMMMYYYY rather than ISO dates.
        match = re.search(r"(\d{2}[A-Za-z]{3}\d{4})_(\d{4,6})", scene_file.name)
        if match:
            return np.datetime64(datetime.strptime(match.group(1).upper() + match.group(2)[:4], "%d%b%Y%H%M"), "ns")
        raise ValueError("cannot determine acquisition timestamp from filename")


class MOSDACStager:
    def __init__(self, directory: str | Path, reader=None, rolling_frames: int = 4, mode: Mode = Mode.historical):
        self.directory = Path(directory); self.directory.mkdir(parents=True, exist_ok=True)
        self.frames = self.directory / "frames"; self.frames.mkdir(exist_ok=True)
        self.reader = reader or HDF5INSATReader(); self.rolling_frames = max(4, rolling_frames); self.mode = Mode(mode)
        self.historical_url = self.directory / "historical.zarr"; self.latest_url = self.directory / "latest.zarr"

    def stage(self, scene_file: Path, scene_id: str | None = None) -> DownloadMetric:
        scene_id = scene_id or scene_file.stem; target = self.frames / f"{re.sub(r'[^A-Za-z0-9._-]', '_', scene_id)}.nc"
        if target.exists(): return DownloadMetric(scene_id, scene_file.stat().st_size, 0.0)
        tracemalloc.start(); started = time.perf_counter()
        try:
            frame = self.reader.read(scene_file)
            # netCDF4 cannot encode a boolean global attribute; the final Zarr
            # stores below preserve the boolean provenance value.
            frame.attrs.update({"provider": "mosdac", "mode": self.mode.value, "is_synthetic": 0})
            SATELLITE_CONTRACT.validate(frame, _metadata(self.mode)); assert_pan_india(frame)
            frame.astype({name: np.float32 for name in SATELLITE_CONTRACT.required_variables}).to_netcdf(target)
            _, peak = tracemalloc.get_traced_memory()
        except Exception as exc:
            target.unlink(missing_ok=True); raise RuntimeError(f"MOSDAC scene {scene_id} is corrupt or could not be decoded ({type(exc).__name__}).") from exc
        finally: tracemalloc.stop()
        self.rebuild_stores()
        return DownloadMetric(scene_id, scene_file.stat().st_size, 0.0, time.perf_counter() - started, peak)

    def rebuild_stores(self):
        paths = sorted(self.frames.glob("*.nc"))
        if not paths: raise RuntimeError("No staged MOSDAC frames available")
        combined = xr.concat([xr.load_dataset(path) for path in paths], dim="time").sortby("time")
        _, indexes = np.unique(combined.time.values, return_index=True); combined = combined.isel(time=np.sort(indexes))
        combined.attrs.update({"provider": "mosdac", "mode": self.mode.value, "is_synthetic": False})
        for path in (self.historical_url, self.latest_url):
            if path.exists(): shutil.rmtree(path)
        combined.to_zarr(self.historical_url, mode="w")
        combined.isel(time=slice(-self.rolling_frames, None)).to_zarr(self.latest_url, mode="w")

    def update_config(self, config_path: str | Path) -> None:
        """Write only staged paths to the shared non-secret satellite config."""
        path = Path(config_path)
        settings = json.loads(path.read_text()) if path.exists() else {}
        settings.setdefault("satellite_provider", "mosdac")
        settings.setdefault("mosdac", {}).update({"historical_url": str(self.historical_url.resolve()),
                                                    "latest_url": str(self.latest_url.resolve()),
                                                    "dataset_ids": list(DATASET_IDS),
                                                    "bounding_box": DEFAULT_BOUNDING_BOX})
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(settings, indent=2) + "\n"); temporary.replace(path)

