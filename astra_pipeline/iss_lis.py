"""Streaming ingestion of historical NASA ISS-LIS V3.0 lightning observations.

NetCDF is the canonical format.  ISS-LIS observations are historical satellite
observations, never a real-time feed or a synthetic lightning proxy.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterable

import numpy as np
import pandas as pd
from netCDF4 import Dataset

PROCESSING_VERSION = "iss_lis_ingest_v1"
INDIA_BBOX = (68.1, 6.7, 97.5, 37.1)  # west, south, east, north; not a polygon
EVENT_COLUMNS = ["timestamp", "latitude", "longitude", "event_id", "flash_id", "source_file", "source_dataset", "orbit_id", "cluster_index", "noise_index", "alert_flag", "radiance", "footprint_km2", "observe_time_seconds"]


@dataclass(frozen=True)
class IngestResult:
    discovered: int
    processed: int
    failed: int
    skipped: int
    observations: int
    india_observations: int
    output_dir: Path


def discover_netcdf_files(input_dir: str | Path) -> list[Path]:
    """Discover only NetCDF inputs; paired HDF4 copies are deliberately ignored."""
    return sorted(Path(input_dir).rglob("*.nc"))


def _variable(dataset: Dataset, name: str) -> np.ndarray:
    if name not in dataset.variables:
        raise ValueError(f"required ISS-LIS variable missing: {name}")
    values = dataset.variables[name][:]
    if np.ma.isMaskedArray(values):
        # Integer quality/index fields can legitimately carry a masked fill
        # value.  Promote only those masked arrays so missingness stays NaN
        # rather than being silently converted to a numeric sentinel.
        if np.issubdtype(values.dtype, np.integer):
            return values.astype(float).filled(np.nan)
        return values.filled(np.nan)
    return np.asarray(values)


def _tai93_to_utc(values: np.ndarray, units: str) -> pd.Series:
    """Convert according to the actual CF-style units declared by the file."""
    expected = "seconds since 1993-01-01 00:00:00.000"
    if units != expected:
        raise ValueError(f"unsupported ISS-LIS time units {units!r}; expected {expected!r}")
    return pd.to_datetime(values, unit="s", origin="1993-01-01", utc=True)


def inspect_netcdf(path: str | Path) -> dict[str, Any]:
    """Return actual schema metadata without loading the full product into memory."""
    with Dataset(path) as ds:
        return {
            "path": str(path), "format": ds.data_model,
            "global_attributes": {key: getattr(ds, key) for key in ds.ncattrs()},
            "dimensions": {key: len(value) for key, value in ds.dimensions.items()},
            "variables": {key: {"dimensions": list(value.dimensions), "dtype": str(value.dtype), "attributes": {attr: getattr(value, attr) for attr in value.ncattrs()}} for key, value in ds.variables.items()},
        }


def extract_events(path: str | Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Extract event-level records from one granule; source fields remain traceable."""
    source = Path(path)
    with Dataset(source) as ds:
        # LIS granules with no detected lightning can legitimately omit the
        # event record structure.  Preserve that as a successful zero-event
        # granule rather than misclassifying it as a corrupt source file.
        if "lightning_event_lat" not in ds.variables:
            orbit = int(np.asarray(ds.variables["orbit_summary_id_number"][:]).item()) if "orbit_summary_id_number" in ds.variables else None
            empty = pd.DataFrame({column: pd.Series(dtype="object") for column in EVENT_COLUMNS})
            empty["timestamp"] = pd.to_datetime(empty["timestamp"], utc=True)
            return empty, {"source_file": source.name, "raw_event_count": 0, "invalid_coordinate_or_time_count": 0, "orbit_id": orbit, "no_event_records": True}
        lat = _variable(ds, "lightning_event_lat").astype(float)
        lon = _variable(ds, "lightning_event_lon").astype(float)
        raw_time = _variable(ds, "lightning_event_TAI93_time").astype(float)
        time_var = ds.variables["lightning_event_TAI93_time"]
        timestamp = _tai93_to_utc(raw_time, getattr(time_var, "units", ""))
        event_address = _variable(ds, "lightning_event_address")
        parent_group = _variable(ds, "lightning_event_parent_address")
        group_address = _variable(ds, "lightning_group_address")
        group_parent_flash = _variable(ds, "lightning_group_parent_address")
        flash_by_group = dict(zip(group_address.tolist(), group_parent_flash.tolist(), strict=True))
        flash_address = np.array([flash_by_group.get(group, np.nan) for group in parent_group])
        orbit = int(np.asarray(ds.variables["orbit_summary_id_number"][:]).item()) if "orbit_summary_id_number" in ds.variables else None
        data: dict[str, Any] = {
            "timestamp": timestamp, "latitude": lat, "longitude": ((lon + 180) % 360) - 180,
            "event_id": [f"{source.stem}:{value}" for value in event_address],
            "flash_id": [f"{source.stem}:{int(value)}" if np.isfinite(value) else None for value in flash_address],
            "source_file": source.name, "source_dataset": "NASA ISS-LIS V3.0", "orbit_id": orbit,
        }
        for destination, variable in (("cluster_index", "lightning_event_cluster_index"), ("noise_index", "lightning_event_noise_index"), ("alert_flag", "lightning_event_alert_flag"), ("radiance", "lightning_event_radiance"), ("footprint_km2", "lightning_event_footprint"), ("observe_time_seconds", "lightning_event_observe_time")):
            if variable in ds.variables:
                data[destination] = _variable(ds, variable)
        frame = pd.DataFrame(data)
    valid = np.isfinite(frame.latitude) & np.isfinite(frame.longitude) & frame.latitude.between(-90, 90) & frame.longitude.between(-180, 180) & frame.timestamp.notna()
    invalid = int((~valid).sum())
    return frame.loc[valid, EVENT_COLUMNS], {"source_file": source.name, "raw_event_count": len(frame), "invalid_coordinate_or_time_count": invalid, "orbit_id": orbit}


def _india_bbox(frame: pd.DataFrame, bbox: tuple[float, float, float, float]) -> pd.DataFrame:
    west, south, east, north = bbox
    return frame[frame.longitude.between(west, east) & frame.latitude.between(south, north)].copy()


def _manifest_path(output: Path) -> Path: return output / "processed_files.csv"


def _read_manifest(output: Path) -> pd.DataFrame:
    path = _manifest_path(output)
    return pd.read_csv(path) if path.exists() else pd.DataFrame(columns=["source_file", "status", "processed_at", "observation_count", "india_observation_count", "error", "processing_version"])


def _write_manifest(manifest: pd.DataFrame, output: Path) -> None:
    target = _manifest_path(output)
    temporary = target.with_suffix(".tmp")
    manifest.sort_values("source_file").to_csv(temporary, index=False)
    # OneDrive/antivirus can briefly hold the existing CSV open on Windows.
    # Retrying the atomic replacement retains a valid old or new manifest;
    # it never exposes a partially-written CSV.
    for attempt in range(100):
        try:
            temporary.replace(target)
            return
        except PermissionError:
            if attempt == 99:
                raise
            time.sleep(.1)


def rebuild_manifest_from_event_partitions(output_dir: str | Path) -> int:
    """Recover successful checkpoint rows after an external process interruption."""
    from pyarrow.parquet import ParquetFile
    output = Path(output_dir); events = output / "events"
    rows = []
    for part in sorted(events.glob("*.parquet")):
        rows.append({"source_file": f"{part.stem}.nc", "status": "success", "processed_at": "recovered_from_event_partition", "observation_count": ParquetFile(part).metadata.num_rows, "india_observation_count": ParquetFile(part).metadata.num_rows, "error": "", "processing_version": PROCESSING_VERSION})
    _write_manifest(pd.DataFrame(rows, columns=["source_file", "status", "processed_at", "observation_count", "india_observation_count", "error", "processing_version"]), output)
    return len(rows)


def _grid_rows(events: pd.DataFrame, resolution: float, interval: str, bbox: tuple[float, float, float, float]) -> pd.DataFrame:
    west, south, _, _ = bbox
    frame = events.copy()
    frame["timestamp"] = frame.timestamp.dt.floor(interval)
    frame["grid_x"] = np.floor((frame.longitude - west) / resolution).astype(int)
    frame["grid_y"] = np.floor((frame.latitude - south) / resolution).astype(int)
    frame["grid_longitude"] = west + (frame.grid_x + .5) * resolution
    frame["grid_latitude"] = south + (frame.grid_y + .5) * resolution
    return frame


def _upsert_grid(connection: sqlite3.Connection, events: pd.DataFrame, resolution: float, interval: str, bbox: tuple[float, float, float, float]) -> None:
    rows = _grid_rows(events, resolution, interval, bbox)
    connection.executemany("INSERT OR IGNORE INTO grid_events(timestamp, grid_x, grid_y, event_id, flash_id) VALUES (?, ?, ?, ?, ?)", ((row.timestamp.isoformat(), int(row.grid_x), int(row.grid_y), row.event_id, row.flash_id) for row in rows.itertuples(index=False)))


def _write_grid_and_features(output: Path, resolution: float, interval: str, bbox: tuple[float, float, float, float]) -> None:
    database = output / "iss_lis_grid.sqlite"
    with sqlite3.connect(database) as connection:
        grid = pd.read_sql_query("SELECT timestamp, grid_x, grid_y, COUNT(*) AS lightning_count, COUNT(DISTINCT flash_id) AS flash_count FROM grid_events GROUP BY timestamp, grid_x, grid_y ORDER BY timestamp, grid_y, grid_x", connection)
    if grid.empty:
        grid = pd.DataFrame(columns=["timestamp", "grid_x", "grid_y", "lightning_count", "flash_count"])
    else:
        west, south, _, _ = bbox
        grid["timestamp"] = pd.to_datetime(grid.timestamp, utc=True)
        grid["latitude"] = south + (grid.grid_y + .5) * resolution
        grid["longitude"] = west + (grid.grid_x + .5) * resolution
        # Cell area approximation is declared, not an observation-derived quantity.
        grid["cell_area_km2_approx"] = (111.32 * resolution) * (111.32 * resolution * np.cos(np.deg2rad(grid.latitude)))
        grid["lightning_density_per_km2"] = grid.lightning_count / grid.cell_area_km2_approx
    grid["source_dataset"] = "NASA ISS-LIS V3.0"
    grid.to_parquet(output / f"lightning_grid_{resolution:g}deg_{interval.replace('min', 'm')}.parquet", index=False)
    if grid.empty:
        grid.to_parquet(output / f"lightning_features_{resolution:g}deg_{interval.replace('min', 'm')}.parquet", index=False); return
    features = grid.sort_values(["grid_y", "grid_x", "timestamp"]).copy()
    seconds = pd.Timedelta(interval).total_seconds()
    for minutes in (5, 10, 30, 60):
        periods = max(1, round(minutes * 60 / seconds))
        features[f"lightning_count_last_{minutes}min"] = features.groupby(["grid_y", "grid_x"])["lightning_count"].transform(lambda values: values.rolling(periods, min_periods=1).sum())
    features["lightning_growth_rate_per_interval"] = features.groupby(["grid_y", "grid_x"])["lightning_count"].diff().fillna(0)
    features["lightning_acceleration_per_interval2"] = features.groupby(["grid_y", "grid_x"])["lightning_growth_rate_per_interval"].diff().fillna(0)
    features["feature_time_rule"] = "uses observations at or before timestamp only; future targets must be joined separately"
    features.to_parquet(output / f"lightning_features_{resolution:g}deg_{interval.replace('min', 'm')}.parquet", index=False)


def ingest_iss_lis(input_dir: str | Path, output_dir: str | Path, *, resolution: float = .25, interval: str = "5min", limit: int | None = None, resume: bool = False, force: bool = False, bbox: tuple[float, float, float, float] = INDIA_BBOX) -> IngestResult:
    """Stream ISS-LIS NetCDF granules into events, grid aggregates, and manifest."""
    if resolution <= 0: raise ValueError("resolution must be positive")
    if pd.Timedelta(interval) <= pd.Timedelta(0, unit="s"): raise ValueError("interval must be positive")
    started = time.monotonic(); output = Path(output_dir); events_dir = output / "events"; output.mkdir(parents=True, exist_ok=True); events_dir.mkdir(exist_ok=True)
    files = discover_netcdf_files(input_dir); selected = files[:limit] if limit else files
    manifest = _read_manifest(output); already = set(manifest.loc[manifest.status == "success", "source_file"]) if resume and not force else set()
    db = sqlite3.connect(output / "iss_lis_grid.sqlite")
    db.execute("CREATE TABLE IF NOT EXISTS grid_events(timestamp TEXT NOT NULL, grid_x INTEGER NOT NULL, grid_y INTEGER NOT NULL, event_id TEXT PRIMARY KEY, flash_id TEXT)")
    processed = failed = skipped = observations = india_observations = 0
    try:
        for file in selected:
            if file.name in already:
                skipped += 1; continue
            now = datetime.now(timezone.utc).isoformat()
            try:
                events, stats = extract_events(file); india = _india_bbox(events, bbox)
                india.to_parquet(events_dir / f"{file.stem}.parquet", index=False)
                _upsert_grid(db, india, resolution, interval, bbox); db.commit()
                record = {"source_file": file.name, "status": "success", "processed_at": now, "observation_count": len(events), "india_observation_count": len(india), "error": "", "processing_version": PROCESSING_VERSION}
                processed += 1; observations += len(events); india_observations += len(india)
            except Exception as exc:
                record = {"source_file": file.name, "status": "failed", "processed_at": now, "observation_count": 0, "india_observation_count": 0, "error": f"{type(exc).__name__}: {exc}", "processing_version": PROCESSING_VERSION}; failed += 1
            manifest = pd.concat([manifest[manifest.source_file != file.name], pd.DataFrame([record])], ignore_index=True)
            _write_manifest(manifest, output)
    finally:
        db.close()
    _write_grid_and_features(output, resolution, interval, bbox)
    report = {"source_dataset": "NASA ISS-LIS", "dataset_version": "V3.0", "data_provenance": "satellite_observation", "observed": True, "forecast": False, "synthetic": False, "canonical_format": "NetCDF", "hdf_status": "HDF4 paired copies are not processed to avoid duplicate observations", "spatial_filter": {"type": "bounding_box_not_exact_india_polygon", "west": bbox[0], "south": bbox[1], "east": bbox[2], "north": bbox[3]}, "grid_resolution_degrees": resolution, "temporal_resolution": interval, "files_discovered": len(files), "files_selected": len(selected), "files_processed": processed, "files_failed": failed, "files_skipped": skipped, "observations_extracted": observations, "india_observations": india_observations, "processing_seconds": round(time.monotonic() - started, 3), "processing_version": PROCESSING_VERSION}
    (output / "quality_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return IngestResult(len(files), processed, failed, skipped, observations, india_observations, output)
