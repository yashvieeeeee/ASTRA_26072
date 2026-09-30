"""Ingestion for Open-Meteo point atmospheric archives.

This module deliberately keeps five-location Open-Meteo data separate from
ASTRA's canonical pan-India grid.  It is historical, model-derived context;
it is not an observation feed, a real-time feed, or a lightning target.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


DEFAULT_DATASET_PATH = Path("data/atmospheric/open_meteo_india_5_locations.csv")
REQUIRED_METADATA_COLUMNS = {"location_id", "latitude", "longitude", "timezone"}
REQUIRED_RECORD_COLUMNS = {"location_id", "time"}

# The raw export has display units in headers.  Match stable Open-Meteo names
# before the unit suffix and leave the raw table untouched.
NORMALIZED_COLUMNS = {
    "temperature_2m": "temperature_2m",
    "relative_humidity_2m": "relative_humidity_2m",
    "dew_point_2m": "dew_point_2m",
    "pressure_msl": "sea_level_pressure",
    "surface_pressure": "surface_pressure",
    "cloud_cover": "cloud_cover_total",
    "cloud_cover_low": "cloud_cover_low",
    "cloud_cover_mid": "cloud_cover_mid",
    "cloud_cover_high": "cloud_cover_high",
    "precipitation": "precipitation",
    "rain": "rain",
    "showers": "showers",
    "wind_speed_10m": "wind_speed_10m",
    "wind_direction_10m": "wind_direction_10m",
    "wind_gusts_10m": "wind_gusts_10m",
    "visibility": "visibility",
    "vapour_pressure_deficit": "vapour_pressure_deficit",
}
# Approximate standard-atmosphere geopotential heights in km.  They permit an
# explicitly labelled temperature lapse-rate proxy when both levels exist.
PRESSURE_HEIGHT_KM = {1000: 0.11, 925: 0.76, 850: 1.46, 700: 3.01, 500: 5.57, 300: 9.16, 200: 11.78}


class AtmosphericValidationError(ValueError):
    """Raised when an archive cannot be represented honestly by this loader."""


@dataclass(frozen=True)
class AtmosphericArchive:
    """Raw and normalised representations plus validation and provenance."""

    raw_metadata: pd.DataFrame
    raw_records: pd.DataFrame
    normalized: pd.DataFrame
    validation: dict[str, Any]
    provenance: dict[str, Any]


def _column_key(name: str) -> str:
    """Extract a provider's stable variable token from a display header."""
    return name.split(" (", 1)[0].strip()


def _read_export(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read Open-Meteo's two-section CSV export without assuming five sites."""
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    data_header_index = next((i for i, line in enumerate(lines) if line.startswith("location_id,time,")), None)
    if data_header_index is None:
        raise AtmosphericValidationError("Open-Meteo CSV is missing its location_id,time data header")
    # Use the literal section boundary. ``nrows`` skips blank lines and can
    # otherwise consume the second header on compact valid exports.
    metadata = pd.read_csv(StringIO("\n".join(lines[:data_header_index])))
    records = pd.read_csv(path, skiprows=data_header_index, encoding="utf-8-sig")
    return metadata, records


def _validate(metadata: pd.DataFrame, records: pd.DataFrame, now: datetime) -> dict[str, Any]:
    missing_metadata = REQUIRED_METADATA_COLUMNS - set(metadata.columns)
    missing_records = REQUIRED_RECORD_COLUMNS - set(records.columns)
    if missing_metadata or missing_records:
        raise AtmosphericValidationError(
            f"Missing metadata columns {sorted(missing_metadata)} or record columns {sorted(missing_records)}"
        )
    if metadata["location_id"].duplicated().any():
        raise AtmosphericValidationError("location_id must be unique in metadata")
    if not metadata["latitude"].between(-90, 90).all() or not metadata["longitude"].between(-180, 180).all():
        raise AtmosphericValidationError("metadata latitude/longitude is outside valid geographic bounds")
    metadata_ids, record_ids = set(metadata.location_id), set(records.location_id)
    unknown_ids = record_ids - metadata_ids
    if unknown_ids:
        raise AtmosphericValidationError(f"records contain location IDs absent from metadata: {sorted(unknown_ids)}")
    parsed = pd.to_datetime(records["time"], errors="coerce")
    if parsed.isna().any():
        raise AtmosphericValidationError(f"{int(parsed.isna().sum())} timestamp(s) cannot be parsed")
    duplicate_count = int(records.duplicated(["location_id", "time"]).sum())
    if duplicate_count:
        raise AtmosphericValidationError(f"{duplicate_count} duplicate location/timestamp record(s) detected")
    # Export timestamps are local to each location's declared timezone, not
    # implicitly UTC.  Compare their UTC representation to the reference.
    future_count = int((_to_utc(records, metadata) > pd.Timestamp(now)).sum())
    value_columns = [column for column in records if column not in REQUIRED_RECORD_COLUMNS]
    missing = records[value_columns].isna().mean().sort_values(ascending=False).to_dict()
    return {
        "duplicate_location_timestamp_records": duplicate_count,
        "future_or_unavailable_records": future_count,
        "fully_missing_records": int(records[value_columns].isna().all(axis=1).sum()),
        "missing_value_percentage": {key: round(float(value) * 100, 4) for key, value in missing.items()},
    }


def _to_utc(records: pd.DataFrame, metadata: pd.DataFrame) -> pd.Series:
    timezone_by_id = metadata.set_index("location_id")["timezone"].to_dict()
    converted: list[pd.Timestamp] = []
    for location_id, raw_timestamp in zip(records.location_id, records.time, strict=True):
        try:
            local = pd.Timestamp(raw_timestamp).tz_localize(ZoneInfo(timezone_by_id[location_id]))
        except (KeyError, TypeError, ValueError) as exc:
            raise AtmosphericValidationError(f"invalid timezone/timestamp for location_id={location_id!r}") from exc
        converted.append(local.tz_convert("UTC"))
    return pd.Series(converted, index=records.index, dtype="datetime64[ns, UTC]")


def _normalise(records: pd.DataFrame, metadata: pd.DataFrame) -> pd.DataFrame:
    output = records[["location_id"]].copy()
    output["timestamp"] = _to_utc(records, metadata)
    output = output.merge(metadata[["location_id", "latitude", "longitude"]], on="location_id", how="left", validate="many_to_one")
    source_by_key = {_column_key(column): column for column in records.columns}
    for source, target in NORMALIZED_COLUMNS.items():
        if source in source_by_key:
            output[target] = pd.to_numeric(records[source_by_key[source]], errors="coerce")
    for key, source in source_by_key.items():
        temperature = re.fullmatch(r"temperature_(\d+)hPa", key)
        humidity = re.fullmatch(r"relative_humidity_(\d+)hPa", key)
        wind_speed = re.fullmatch(r"wind_speed_(\d+)hPa", key)
        if temperature:
            output[f"temperature_{temperature.group(1)}hpa"] = pd.to_numeric(records[source], errors="coerce")
        elif humidity:
            output[f"relative_humidity_{humidity.group(1)}hpa"] = pd.to_numeric(records[source], errors="coerce")
        elif wind_speed:
            output[f"wind_speed_{wind_speed.group(1)}hpa"] = pd.to_numeric(records[source], errors="coerce")
    _add_derived_features(output)
    return output.sort_values(["location_id", "timestamp"], kind="stable").reset_index(drop=True)


def _add_derived_features(frame: pd.DataFrame) -> None:
    if {"wind_speed_10m", "wind_direction_10m"}.issubset(frame):
        radians = np.deg2rad(frame["wind_direction_10m"])
        # Meteorological direction is where wind comes from; u/v are eastward/northward.
        frame["wind_u_10m"] = -frame["wind_speed_10m"] * np.sin(radians)
        frame["wind_v_10m"] = -frame["wind_speed_10m"] * np.cos(radians)
    # Descending pressure moves from the lower atmosphere upward.
    temperatures = sorted((int(match.group(1)) for column in frame for match in [re.fullmatch(r"temperature_(\d+)hpa", column)] if match), reverse=True)
    for lower, upper in zip(temperatures, temperatures[1:]):
        lower_column, upper_column = f"temperature_{lower}hpa", f"temperature_{upper}hpa"
        frame[f"temperature_difference_{lower}_{upper}hpa"] = frame[lower_column] - frame[upper_column]
        if lower in PRESSURE_HEIGHT_KM and upper in PRESSURE_HEIGHT_KM:
            frame[f"temperature_lapse_rate_{lower}_{upper}hpa_c_per_km"] = (
                frame[lower_column] - frame[upper_column]
            ) / (PRESSURE_HEIGHT_KM[upper] - PRESSURE_HEIGHT_KM[lower])
    humidities = sorted((int(match.group(1)) for column in frame for match in [re.fullmatch(r"relative_humidity_(\d+)hpa", column)] if match), reverse=True)
    for lower, upper in zip(humidities, humidities[1:]):
        frame[f"relative_humidity_difference_{lower}_{upper}hpa"] = (
            frame[f"relative_humidity_{lower}hpa"] - frame[f"relative_humidity_{upper}hpa"]
        )
    # This archive contains pressure-level speeds but no matching directions,
    # so vector vertical shear is intentionally not calculated.


def load_open_meteo_atmospheric_archive(path: str | Path = DEFAULT_DATASET_PATH, *, now: datetime | None = None) -> AtmosphericArchive:
    """Load, validate and normalise a historical/model-derived Open-Meteo export.

    Missing measurements remain ``NaN`` throughout.  No interpolation, forward
    fill, or synthetic future values are applied.
    """
    dataset_path = Path(path)
    if not dataset_path.exists():
        raise FileNotFoundError(dataset_path)
    metadata, raw_records = _read_export(dataset_path)
    reference_time = now or datetime.now(timezone.utc)
    validation = _validate(metadata, raw_records, reference_time)
    normalized = _normalise(raw_records, metadata)
    provenance = {
        "source": "Open-Meteo",
        "data_type": "atmospheric",
        "data_provenance": "reanalysis/model-derived",
        "observed": False,
        "forecast": False,
        "synthetic": False,
        "locations": int(metadata.location_id.nunique()),
        "temporal_resolution": "hourly",
    }
    return AtmosphericArchive(metadata, raw_records, normalized, validation, provenance)


def atmospheric_preview(path: str | Path = DEFAULT_DATASET_PATH, *, now: datetime | None = None) -> dict[str, Any]:
    """Return JSON-serialisable archive statistics for a CLI, endpoint, or job."""
    archive = load_open_meteo_atmospheric_archive(path, now=now)
    latest = archive.normalized.groupby("location_id")["timestamp"].max()
    return {
        "provenance": archive.provenance,
        "records": int(len(archive.normalized)),
        "date_range_utc": {"start": archive.normalized.timestamp.min().isoformat(), "end": archive.normalized.timestamp.max().isoformat()},
        "latest_available_timestamp_utc_by_location": {str(key): value.isoformat() for key, value in latest.items()},
        "available_variables": [column for column in archive.normalized.columns if column not in {"location_id", "latitude", "longitude", "timestamp"}],
        "validation": archive.validation,
    }
