"""Credential-safe EUMETSAT IODC download, decode, and staging path.

Network access is isolated in :class:`EUMETSATIODCDownloader`; readers are
pure file-to-xarray transforms so CI can use tiny synthetic fixtures.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import tracemalloc
from typing import Iterable, Protocol
import zipfile

import numpy as np
import xarray as xr

from .adapters import SATELLITE_CONTRACT
from .domain import LATITUDES, LONGITUDES, assert_pan_india

IODC_COLLECTION = "EO:EUM:DAT:MSG:HRSEVIRI-IODC"
CHANNELS = {"IR_108": "ir1_brightness_temperature", "IR_120": "tir1_brightness_temperature", "WV_073": "wv_brightness_temperature"}


class SatelliteSceneReader(ABC):
    """Provider file -> canonical ASTRA satellite frame.  Data Tailor can implement this later."""
    @abstractmethod
    def read(self, scene_file: Path) -> xr.Dataset: ...


class SatpySEVIRIReader(SatelliteSceneReader):
    """Decode native HRSEVIRI archives and spatially resample to ASTRA's fixed grid."""
    def read(self, scene_file: Path) -> xr.Dataset:
        try:
            from satpy import Scene
            from pyresample import create_area_def
        except ImportError as exc:  # Avoid making sample/test mode depend on Satpy.
            raise RuntimeError("Satpy is required for native IODC decoding. Install the pinned production dependencies.") from exc
        scene = Scene(filenames=[str(scene_file)], reader="seviri_l1b_native")
        scene.load(list(CHANNELS), calibration="brightness_temperature")
        area = create_area_def("astra_pan_india", {"proj": "longlat", "datum": "WGS84"},
                               area_extent=(68.0, 6.0, 98.0, 38.0), shape=(len(LATITUDES), len(LONGITUDES)), units="degrees")
        resampled = scene.resample(area)
        time_value = next((resampled[name].attrs.get("start_time") for name in CHANNELS if resampled[name].attrs.get("start_time")), None)
        if time_value is None:
            raise ValueError(f"{scene_file.name}: native scene has no acquisition time")
        data = {}
        for source, target in CHANNELS.items():
            values = np.asarray(resampled[source].values)
            # Geographic area definitions conventionally enumerate north-to-south.
            if values.shape == (len(LATITUDES), len(LONGITUDES)):
                values = values[::-1, :]
            data[target] = (("time", "latitude", "longitude"), values[np.newaxis, ...], {"units": "K"})
        output = xr.Dataset(data, coords={"time": [np.datetime64(time_value, "ns")], "latitude": LATITUDES, "longitude": LONGITUDES},
                            attrs={"satellite_provider": "eumetsat_iodc", "collection": IODC_COLLECTION})
        SATELLITE_CONTRACT.validate(output, _metadata())
        assert_pan_india(output)
        return output


def _metadata():
    # Local import avoids a contract/model import cycle at module import time.
    from .contracts import Mode, SourceMetadata
    return SourceMetadata(source=SATELLITE_CONTRACT.name, mode=Mode.realtime, spatial_representation="grid",
                          variables=list(SATELLITE_CONTRACT.required_variables), units=SATELLITE_CONTRACT.required_variables)


class Product(Protocol):
    @property
    def id(self) -> str: ...
    def open(self): ...


@dataclass
class DownloadMetric:
    product_id: str
    bytes_downloaded: int
    download_seconds: float
    decode_subset_seconds: float = 0.0
    peak_memory_bytes: int = 0


class EUMETSATIODCDownloader:
    """Uses EUMDAC's local credential store; it never logs or persists secrets."""
    def __init__(self, raw_directory: str | Path, retries: int = 3, backoff_seconds: float = 1.0):
        self.raw_directory = Path(raw_directory); self.raw_directory.mkdir(parents=True, exist_ok=True)
        self.retries, self.backoff_seconds = retries, backoff_seconds

    @staticmethod
    def credentials_path() -> Path:
        return Path(os.getenv("EUMDAC_CONFIG_DIR", Path.home() / ".eumdac")) / "credentials"

    def _datastore(self):
        path = self.credentials_path()
        if not path.is_file():
            raise RuntimeError(f"EUMETSAT credentials are missing: run `eumdac --set-credentials` to create {path}. Credentials are never read from ASTRA config.")
        try:
            import eumdac
            from eumdac.cli_helpers import load_credentials
        except ImportError as exc:
            raise RuntimeError("eumdac is required for EUMETSAT IODC ingestion. Install the pinned production dependencies.") from exc
        # EUMDAC owns parsing and token renewal; do not print the returned credentials/token.
        return eumdac.DataStore(eumdac.AccessToken(load_credentials()))

    def find(self, start: datetime, end: datetime) -> Iterable[Product]:
        return self._datastore().get_collection(IODC_COLLECTION).search(dtstart=start, dtend=end)

    def raw_path(self, product_id: str) -> Path:
        return self.raw_directory / f"{re.sub(r'[^A-Za-z0-9._-]', '_', product_id)}.zip"

    def download(self, product: Product) -> DownloadMetric | None:
        product_id = str(product)
        destination = self.raw_path(product_id)
        if destination.exists() and destination.stat().st_size:
            return None
        temporary = destination.with_suffix(".part")
        for attempt in range(self.retries):
            try:
                started = time.perf_counter()
                with product.open() as stream, temporary.open("wb") as output:
                    shutil.copyfileobj(stream, output)
                temporary.replace(destination)
                return DownloadMetric(product_id, destination.stat().st_size, time.perf_counter() - started)
            except Exception as exc:
                temporary.unlink(missing_ok=True)
                if attempt + 1 == self.retries:
                    # Deliberately do not include exception repr: upstream errors may carry a URL token.
                    raise RuntimeError(f"IODC download failed for scene {product_id} after {self.retries} attempts ({type(exc).__name__}).") from exc
                time.sleep(self.backoff_seconds * (2 ** attempt))
        return None


class IODCStager:
    """Stages canonical frames, explicitly aligns 15-minute scans to 30-minute buckets, and keeps a rolling Zarr store."""
    def __init__(self, directory: str | Path, reader: SatelliteSceneReader, rolling_frames: int = 4):
        self.directory = Path(directory); self.directory.mkdir(parents=True, exist_ok=True)
        self.frames = self.directory / "frames"; self.frames.mkdir(exist_ok=True)
        self.reader, self.rolling_frames = reader, max(4, rolling_frames)
        self.latest_url, self.historical_url = self.directory / "latest.zarr", self.directory / "historical.zarr"

    def stage(self, scene_file: Path, scene_id: str | None = None) -> DownloadMetric:
        scene_id = scene_id or scene_file.stem
        # Product IDs/timestamps can contain ':' (an NTFS alternate-data-stream
        # separator) or '/' and must never become raw Windows path components.
        safe_scene_id = re.sub(r"[^A-Za-z0-9._-]", "_", scene_id)
        target = self.frames / f"{safe_scene_id}.nc"
        if target.exists():
            return DownloadMetric(scene_id, scene_file.stat().st_size, 0.0)
        tracemalloc.start(); started = time.perf_counter()
        try:
            frame = self._read_native_scene(scene_file)
            SATELLITE_CONTRACT.validate(frame, _metadata()); assert_pan_india(frame)
            # Missing 30-minute buckets must be representable as NaN; native
            # brightness temperatures can otherwise arrive as integer arrays.
            frame = frame.astype({name: np.float32 for name in SATELLITE_CONTRACT.required_variables})
            frame.to_netcdf(target)
            current, peak = tracemalloc.get_traced_memory()
        except Exception as exc:
            target.unlink(missing_ok=True)
            raise RuntimeError(f"IODC scene {scene_id} is corrupt or could not be decoded ({type(exc).__name__}).") from exc
        finally:
            tracemalloc.stop()
        self.rebuild_stores()
        return DownloadMetric(scene_id, scene_file.stat().st_size, 0.0, time.perf_counter() - started, peak)

    def _read_native_scene(self, scene_file: Path) -> xr.Dataset:
        """Safely unpack EUMDAC's product archive before handing its .nat scene to Satpy."""
        if scene_file.suffix.lower() != ".zip":
            return self.reader.read(scene_file)
        if not zipfile.is_zipfile(scene_file):
            raise ValueError("download is not a valid EUMETSAT product zip")
        with tempfile.TemporaryDirectory(prefix="astra-iodc-") as temporary:
            root = Path(temporary)
            with zipfile.ZipFile(scene_file) as archive:
                members = [info for info in archive.infolist() if info.filename.lower().endswith(".nat")]
                if not members:
                    raise ValueError("EUMETSAT product has no native .nat scene")
                member = members[0]
                target = root / Path(member.filename).name
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
            return self.reader.read(target)

    def _all_frames(self) -> xr.Dataset:
        paths = sorted(self.frames.glob("*.nc"))
        if not paths: raise RuntimeError("No staged IODC frames available")
        datasets = [xr.load_dataset(path) for path in paths]
        combined = xr.concat(datasets, dim="time").sortby("time")
        _, index = np.unique(combined.time.values, return_index=True)
        return combined.isel(time=np.sort(index))

    @staticmethod
    def align_30_minutes(dataset: xr.Dataset) -> xr.Dataset:
        """Nearest observed scan only; missing 30-minute buckets remain NaN and are status-marked."""
        times = dataset.time.values.astype("datetime64[ns]")
        start = times.min().astype("datetime64[30m]"); end = times.max().astype("datetime64[30m]")
        buckets = np.arange(start, end + np.timedelta64(30, "m"), np.timedelta64(30, "m"))
        aligned = dataset.reindex(time=buckets, method="nearest", tolerance=np.timedelta64(15, "m"))
        missing = [str(t) for t in aligned.time.values[np.isnan(aligned[next(iter(CHANNELS.values()))]).all(("latitude", "longitude")).values]]
        aligned.attrs.update(dataset.attrs)
        aligned.attrs["source_status"] = {"state": "delayed" if missing else "complete", "missing_buckets_utc": missing, "temporal_interpolation": "never"}
        return aligned

    def rebuild_stores(self) -> None:
        historical = self.align_30_minutes(self._all_frames())
        for path in (self.historical_url, self.latest_url):
            if path.exists(): shutil.rmtree(path)
        historical.to_zarr(self.historical_url, mode="w")
        historical.isel(time=slice(-self.rolling_frames, None)).to_zarr(self.latest_url, mode="w")

    def update_config(self, config_path: str | Path) -> None:
        path = Path(config_path); settings = json.loads(path.read_text()) if path.exists() else {}
        settings.setdefault("satellite_provider", "eumetsat_iodc")
        settings.setdefault("eumetsat_iodc", {}).update({"latest_url": str(self.latest_url.resolve()), "historical_url": str(self.historical_url.resolve())})
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(settings, indent=2) + "\n"); temporary.replace(path)
