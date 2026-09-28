"""Transparent nowcasting baselines operating solely on Phase 1 fused tensors."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import xarray as xr
from scipy.ndimage import uniform_filter, map_coordinates
from .domain import assert_pan_india

LEAD_MINUTES = np.array([10, 20, 30, 40, 50, 60], dtype=int)

@dataclass(frozen=True)
class BaselineConfig:
    radar_feature: str = "precipitation_rate"
    # Phase 1 normalises its fused feature cube, so this is a z-score threshold.
    # Calibrate it on training data and keep it fixed for the held-out test period.
    event_threshold: float = 0.5
    lk_window: int = 9

def radar_proxy(fused: xr.Dataset, feature: str = "precipitation_rate") -> xr.DataArray:
    """Select the radar-proxy channel without reading any external source."""
    if "atmospheric_state" not in fused or "feature" not in fused.coords:
        raise ValueError("Expected Phase 1 fused Dataset with atmospheric_state and feature coordinates")
    if feature not in fused.feature.values:
        raise ValueError(f"Radar feature {feature!r} absent; available: {list(fused.feature.values)}")
    field = fused.atmospheric_state.sel(feature=feature).transpose("time", "latitude", "longitude")
    assert_pan_india(field.to_dataset(name="radar_proxy"))
    return field

def persistence_forecast(last_observation: xr.DataArray, lead_minutes=LEAD_MINUTES) -> xr.DataArray:
    """Persistence: the most recent state is the forecast for every lead."""
    return xr.concat([last_observation] * len(lead_minutes), dim="lead_minutes").assign_coords(lead_minutes=lead_minutes)

def lucas_kanade_flow(previous: np.ndarray, current: np.ndarray, window: int = 9) -> tuple[np.ndarray, np.ndarray]:
    """Dense Lucas–Kanade displacement in pixels per observed frame (x, y)."""
    previous, current = np.nan_to_num(previous), np.nan_to_num(current)
    iy, ix = np.gradient((previous + current) / 2.0)
    it = current - previous
    sxx = uniform_filter(ix * ix, size=window)
    syy = uniform_filter(iy * iy, size=window)
    sxy = uniform_filter(ix * iy, size=window)
    sxt = uniform_filter(ix * it, size=window); syt = uniform_filter(iy * it, size=window)
    det = sxx * syy - sxy * sxy
    # A small texture threshold avoids unstable velocity in clear-sky areas.
    stable = np.abs(det) > 1e-7
    u = np.where(stable, (sxy * syt - syy * sxt) / det, 0.0)
    v = np.where(stable, (sxy * sxt - sxx * syt) / det, 0.0)
    return np.clip(u, -10, 10), np.clip(v, -10, 10)

def optical_flow_forecast(previous: xr.DataArray, current: xr.DataArray, cadence_minutes: float,
                          lead_minutes=LEAD_MINUTES, window: int = 9) -> xr.DataArray:
    """Advect the latest radar proxy using Lucas–Kanade flow from its two last frames."""
    if cadence_minutes <= 0: raise ValueError("Observation cadence must be positive")
    u, v = lucas_kanade_flow(np.asarray(previous), np.asarray(current), window)
    yy, xx = np.indices(current.shape)
    forecasts = []
    for lead in lead_minutes:
        factor = lead / cadence_minutes
        # Backward sampling produces a forward advected field without creating new intensity.
        warped = map_coordinates(np.asarray(current), [yy - v*factor, xx - u*factor], order=1, mode="nearest")
        forecasts.append(xr.DataArray(warped, coords=current.coords, dims=current.dims))
    return xr.concat(forecasts, dim="lead_minutes").assign_coords(lead_minutes=lead_minutes)

def categorical_scores(forecast: xr.DataArray, truth: xr.DataArray, threshold: float) -> dict[str, float]:
    """POD, FAR and CSI for one paired pan-India field; missing cells are excluded."""
    valid = np.isfinite(forecast) & np.isfinite(truth)
    f = np.asarray(forecast)[valid] >= threshold; o = np.asarray(truth)[valid] >= threshold
    hits = np.count_nonzero(f & o); misses = np.count_nonzero(~f & o); false_alarms = np.count_nonzero(f & ~o)
    return {"pod": hits/(hits+misses) if hits+misses else np.nan,
            "far": false_alarms/(hits+false_alarms) if hits+false_alarms else np.nan,
            "csi": hits/(hits+misses+false_alarms) if hits+misses+false_alarms else np.nan,
            "samples": int(valid.sum())}

class NowcastBaseline:
    def __init__(self, config: BaselineConfig = BaselineConfig()): self.config = config

    def forecasts_at(self, fused: xr.Dataset, origin_index: int) -> xr.Dataset:
        field = radar_proxy(fused, self.config.radar_feature)
        if origin_index < 1: raise ValueError("Optical flow needs two observations; origin_index must be >= 1")
        cadence = float((field.time.values[origin_index] - field.time.values[origin_index-1]) / np.timedelta64(1, "m"))
        latest = field.isel(time=origin_index)
        return xr.Dataset({"persistence": persistence_forecast(latest),
            "optical_flow": optical_flow_forecast(field.isel(time=origin_index-1), latest, cadence, window=self.config.lk_window)}).assign_coords(origin_time=field.time.values[origin_index])

    def evaluate(self, fused: xr.Dataset, test_start: np.datetime64 | None = None) -> xr.Dataset:
        """Score all valid test origins. Leads lacking an exact observed target remain NaN, never fabricated."""
        field = radar_proxy(fused, self.config.radar_feature)
        assert_pan_india(field.to_dataset(name="radar_proxy"))
        times = field.time.values; test_start = np.datetime64(test_start) if test_start is not None else times[0]
        accum = {method: {int(lead): [] for lead in LEAD_MINUTES} for method in ("persistence", "optical_flow")}
        for origin in range(1, len(times)):
            predicted = self.forecasts_at(fused, origin)
            for lead in LEAD_MINUTES:
                target_time = times[origin] + np.timedelta64(int(lead), "m")
                matches = np.flatnonzero(times == target_time)
                if not len(matches) or target_time < test_start: continue
                truth = field.isel(time=int(matches[0]))
                for method in accum:
                    accum[method][int(lead)].append(categorical_scores(predicted[method].sel(lead_minutes=lead), truth, self.config.event_threshold))
        methods=list(accum); metrics=["pod","far","csi","samples"]
        values=np.full((len(methods),len(LEAD_MINUTES),len(metrics)),np.nan)
        origins=np.zeros((len(methods),len(LEAD_MINUTES)),dtype=int)
        for mi, method in enumerate(methods):
            for li, lead in enumerate(LEAD_MINUTES):
                scores=accum[method][int(lead)]; origins[mi,li]=len(scores)
                if scores:
                    for ki, metric in enumerate(metrics): values[mi,li,ki]=np.mean([s[metric] for s in scores])
        result=xr.Dataset({"score":(("method","lead_minutes","metric"),values),"evaluated_origins":(("method","lead_minutes"),origins)},coords={"method":methods,"lead_minutes":LEAD_MINUTES,"metric":metrics})
        result.attrs.update({"radar_feature":self.config.radar_feature,"event_threshold_zscore":self.config.event_threshold,
            "missing_leads": "NaN means no exact verifying observation at that lead; do not compare it as a score."})
        return result
