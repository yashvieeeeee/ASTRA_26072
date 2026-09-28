from __future__ import annotations
import numpy as np
import xarray as xr
from .adapters import SourceAdapter, default_adapters
from .contracts import Mode, FusedOutputMetadata
from .domain import LATITUDES, LONGITUDES, assert_pan_india

class PreprocessingPipeline:
    """Lazy, schema-gated fusion onto ASTRA's non-negotiable pan-India grid."""
    def __init__(self, adapters: list[SourceAdapter] | None = None):
        self.adapters = adapters or default_adapters()

    def run(self, mode: Mode | str = Mode.sample) -> xr.Dataset:
        raw = [(adapter, adapter.load(mode)) for adapter in self.adapters]
        grid_sources = [self._quality_check(a, ds) for a, ds in raw]
        timeline = self._timeline(grid_sources)
        aligned = [self._align(ds, timeline) for ds in grid_sources]
        features = self._derive_and_normalize(aligned)
        fused = xr.concat(features, dim="feature").transpose("time", "feature", "latitude", "longitude")
        fused = fused.assign_coords(feature=[f.name for f in features]).to_dataset(name="atmospheric_state")
        fused.attrs.update(FusedOutputMetadata(features=[str(x) for x in fused.feature.values]).model_dump(mode="json"))
        fused.attrs["source_status"] = {
            a.contract.name: {"synthetic": a.metadata.is_synthetic, "is_synthetic": a.metadata.is_synthetic,
                              "mode": a.metadata.mode.value, "pending": a.contract.pending_source,
                              **(ds.attrs.get("source_status", {}) if a.contract.name == "insat_3d_3dr" else {})}
            for a, ds in raw
        }
        assert_pan_india(fused)
        return fused

    def build_sequences(self, fused: xr.Dataset, input_window_minutes: int = 60) -> xr.Dataset:
        """Construct input windows; 60 minutes at 30-minute buckets is four frames inclusive."""
        if input_window_minutes != 60: raise ValueError("ASTRA currently fixes its input window at the PRD-required last hour (60 minutes)")
        assert_pan_india(fused)
        field = fused["atmospheric_state"]
        frames = 4
        if field.sizes["time"] < frames: raise ValueError("Need at least four 30-minute buckets to build a last-hour input")
        windows = [field.isel(time=slice(i, i + frames)).rename({"time":"input_step"}).assign_coords(input_step=np.arange(frames)) for i in range(field.sizes["time"]-frames+1)]
        out = xr.concat(windows, dim="sequence").assign_coords(sequence=field.time.values[frames-1:]).to_dataset(name="inputs")
        assert_pan_india(out)
        return out

    def _quality_check(self, adapter, dataset):
        adapter.contract.validate(dataset, adapter.metadata)
        if not np.all(np.diff(dataset.time.values.astype("datetime64[ns]").astype("int64")) > 0):
            raise ValueError(f"{adapter.contract.name}: timestamps must be strictly increasing")
        if adapter.contract.representation == "grid":
            for coord in ("latitude", "longitude"):
                if not np.all(np.diff(dataset[coord].values) > 0): raise ValueError(f"{adapter.contract.name}: {coord} must increase")
            # Regridding must not manufacture claimed national coverage from a regional feed.
            if (dataset.latitude.min() > LATITUDES[0] or dataset.latitude.max() < LATITUDES[-1]
                    or dataset.longitude.min() > LONGITUDES[0] or dataset.longitude.max() < LONGITUDES[-1]):
                raise ValueError(f"Pan-India coverage violation: {adapter.contract.name} does not span 6–38N / 68–98E")
            return dataset
        return self._points_to_grid(dataset, adapter.contract.name)

    def _timeline(self, datasets):
        # Union lets delayed data remain explicit NaNs instead of silently shrinking time coverage.
        return np.unique(np.concatenate([d.time.values for d in datasets]))

    def _align(self, dataset, timeline):
        spatial = dataset.interp(latitude=LATITUDES, longitude=LONGITUDES, method="linear")
        # 15 min tolerance makes 30-min buckets deterministic and flags a delayed source as NaN.
        return spatial.reindex(time=timeline, method="nearest", tolerance=np.timedelta64(15, "m"))

    def _points_to_grid(self, dataset, source):
        """Bin observations, not interpolate them; only point-sized station/strike batches materialise."""
        result = xr.Dataset(coords={"time":dataset.time, "latitude":LATITUDES, "longitude":LONGITUDES})
        lat = np.asarray(dataset.latitude); lon = np.asarray(dataset.longitude)
        iy = np.rint((lat - LATITUDES[0]) / .25).astype(int); ix = np.rint((lon - LONGITUDES[0]) / .25).astype(int)
        valid = (iy >= 0)&(iy < len(LATITUDES))&(ix >= 0)&(ix < len(LONGITUDES))
        for name, variable in dataset.data_vars.items():
            cube = np.full((dataset.sizes["time"],len(LATITUDES),len(LONGITUDES)), np.nan)
            # Point feeds are bounded records per interval; gridded feeds stay lazy everywhere.
            for t in range(dataset.sizes["time"]):
                values=np.asarray(variable.isel(time=t)); sums=np.zeros_like(cube[t]); counts=np.zeros_like(cube[t])
                np.add.at(sums,(iy[valid],ix[valid]),values[valid]); np.add.at(counts,(iy[valid],ix[valid]),1)
                cube[t]=np.divide(sums,counts,out=np.full_like(sums,np.nan),where=counts>0)
            result[name]=(("time","latitude","longitude"),cube,variable.attrs)
        result.attrs.update(dataset.attrs); result.attrs["point_to_grid_source"] = source
        return result

    def _derive_and_normalize(self, datasets):
        variables=[]
        for ds in datasets:
            for name, da in ds.data_vars.items(): variables.append(self._normalize(da.rename(name)))
            if {"u_1000","v_1000","u_500","v_500"}.issubset(ds.data_vars):
                shear=np.hypot(ds.u_500-ds.u_1000,ds.v_500-ds.v_1000).rename("bulk_shear_1000_500")
                shear.attrs["units"]="m s-1"; variables.append(self._normalize(shear))
        return variables

    @staticmethod
    def _normalize(da):
        # xarray/Dask reductions remain lazy for Zarr-backed arrays.
        valid = da.notnull()
        count = valid.sum()
        mean = da.fillna(0).sum() / xr.where(count == 0, 1, count)
        # Explicit masked variance avoids eager NumPy's all-NaN-slice warnings.
        variance = ((da - mean).where(valid, 0) ** 2).sum() / xr.where(count == 0, 1, count)
        std = np.sqrt(variance)
        return ((da-mean)/xr.where(std == 0, 1, std)).fillna(0).rename(da.name)
