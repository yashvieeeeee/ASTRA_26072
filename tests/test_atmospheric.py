from datetime import datetime, timezone

import pandas as pd
import pytest

from astra_pipeline.atmospheric import AtmosphericValidationError, atmospheric_preview, load_open_meteo_atmospheric_archive


def _export(path, rows, *, duplicate=False):
    path.write_text(
        "location_id,latitude,longitude,elevation,utc_offset_seconds,timezone,timezone_abbreviation\n"
        "0,19.08,72.85,6,19800,Asia/Kolkata,IST\n\n"
        "location_id,time,temperature_2m (°C),wind_speed_10m (km/h),wind_direction_10m (°),temperature_1000hPa (°C),temperature_500hPa (°C)\n"
        + "\n".join(rows + (rows[:1] if duplicate else []))
        + "\n",
        encoding="utf-8",
    )


def test_open_meteo_archive_preserves_raw_and_normalises_derived_features(tmp_path):
    source = tmp_path / "open-meteo.csv"
    _export(source, ["0,2026-07-16T01:00,27,10,90,20,-5", "0,2026-07-16T00:00,26,8,180,21,-4"])
    archive = load_open_meteo_atmospheric_archive(source, now=datetime(2026, 8, 1, tzinfo=timezone.utc))
    assert archive.raw_records.columns[2] == "temperature_2m (°C)"
    assert archive.normalized.timestamp.dt.tz is not None
    assert archive.normalized.timestamp.is_monotonic_increasing
    assert archive.normalized.loc[0, "wind_u_10m"] == pytest.approx(0)
    assert archive.normalized.loc[0, "wind_v_10m"] == pytest.approx(8)
    assert "temperature_lapse_rate_500_1000hpa_c_per_km" not in archive.normalized
    assert "temperature_lapse_rate_1000_500hpa_c_per_km" in archive.normalized
    assert archive.provenance["observed"] is False


def test_open_meteo_archive_rejects_duplicate_records(tmp_path):
    source = tmp_path / "duplicates.csv"
    _export(source, ["0,2026-07-16T00:00,26,8,180,21,-4"], duplicate=True)
    with pytest.raises(AtmosphericValidationError, match="duplicate"):
        load_open_meteo_atmospheric_archive(source)


def test_open_meteo_preview_reports_future_and_missing_without_filling(tmp_path):
    source = tmp_path / "future.csv"
    _export(source, ["0,2026-10-16T00:00,,,,,"])
    preview = atmospheric_preview(source, now=datetime(2026, 9, 30, tzinfo=timezone.utc))
    assert preview["validation"]["future_or_unavailable_records"] == 1
    assert preview["validation"]["fully_missing_records"] == 1
    assert pd.isna(load_open_meteo_atmospheric_archive(source).normalized.loc[0, "temperature_2m"])
