"""Pluggable source adapters. Sample mode is intentionally self-contained."""
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
import json, os
import numpy as np
import xarray as xr
from .contracts import Mode, SourceMetadata, DatasetContract
from .domain import LATITUDES, LONGITUDES, RESOLUTION

TIMES = np.array(["2026-05-20T00:00", "2026-05-20T00:30", "2026-05-20T01:00", "2026-05-20T01:30", "2026-05-20T02:00"], dtype="datetime64[ns]")

# This is the fixed downstream satellite interface.  Provider-specific channel
# names are normalised to it before validation, so fusion never needs to know
# whether the data came from MOSDAC or EUMETSAT.
SATELLITE_CONTRACT = DatasetContract(
    name="insat_3d_3dr",
    representation="grid",
    required_variables={
        "ir1_brightness_temperature": "K",
        "tir1_brightness_temperature": "K",
        "wv_brightness_temperature": "K",
    },
)
# ``eumetsat`` is the user-facing provider switch; the longer spelling remains
# accepted for existing configurations.
SATELLITE_PROVIDERS = {"eumetsat", "eumetsat_iodc", "mosdac"}
NWP_REALTIME_PROVIDERS = {"gfs_herbie", "open_meteo"}
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

def _grid(vars: dict[str, tuple[np.ndarray, str]], source: str) -> xr.Dataset:
    yy, xx = np.meshgrid(LATITUDES, LONGITUDES, indexing="ij")
    data = {}
    for name, (base, unit) in vars.items():
        arr = np.stack([base * (1 + .05 * t) for t in range(len(TIMES))])
        data[name] = (("time", "latitude", "longitude"), arr, {"units": unit})
    return xr.Dataset(data, coords={"time": TIMES, "latitude": LATITUDES, "longitude": LONGITUDES}, attrs={"source": source})

class SourceAdapter(ABC):
    contract: DatasetContract
    @property
    def metadata(self) -> SourceMetadata:
        return SourceMetadata(source=self.contract.name, mode=self._mode, is_synthetic=self.contract.is_synthetic or self._mode is Mode.sample,
          spatial_representation=self.contract.representation, variables=list(self.contract.required_variables),
          units=self.contract.required_variables, pending_source=self.contract.pending_source)
    def load(self, mode: Mode | str = Mode.sample) -> xr.Dataset:
        self._mode = Mode(mode)
        dataset = self.sample() if self._mode is Mode.sample else self.production(self._mode)
        dataset.attrs.update({"mode": self._mode.value, "is_synthetic": self.metadata.is_synthetic})
        self.contract.validate(dataset, self.metadata)
        return dataset
    @abstractmethod
    def sample(self) -> xr.Dataset: ...
    def production(self, mode: Mode) -> xr.Dataset:
        raise RuntimeError(f"{self.contract.name} {mode.value} needs its configured production endpoint; sample mode is credential-free.")

class GPMAdapter(SourceAdapter):
    contract = DatasetContract(name="gpm_imerg", representation="grid", required_variables={"precipitation_rate": "mm hr-1"})
    def sample(self):
        y, x = np.meshgrid(LATITUDES, LONGITUDES, indexing="ij")
        rain = 18 * np.exp(-((y-25)**2 + (x-82)**2)/18)
        return _grid({"precipitation_rate": (rain, "mm hr-1")}, "GPM_3IMERGHH sample")
    def production(self, mode):
        product = "GPM_3IMERGHH" if mode is Mode.historical else "GPM_3IMERGHHE"
        if not Path.home().joinpath(".netrc").exists(): raise RuntimeError("GPM requires NASA Earthdata credentials in ~/.netrc")
        return _open_endpoint(os.getenv("ASTRA_GPM_ZARR_URL"), product)

def _satellite_settings() -> dict:
    """Read the shared, non-secret satellite configuration when it is present."""
    # ASTRA_MOSDAC_CONFIG is deliberately excluded: it is a credentials-only
    # file and must never double as a repository configuration file.
    path = Path(os.getenv("ASTRA_SATELLITE_CONFIG", "config.json"))
    return json.loads(path.read_text()) if path.exists() else {}

def nwp_realtime_provider() -> str:
    """Return the explicitly configurable real-time NWP provider.

    GFS via Herbie is the gridded operational default. Open-Meteo remains a
    point-query fallback and is intentionally not allowed to service the full
    pan-India NWP contract.
    """
    provider = os.getenv("ASTRA_NWP_REALTIME_PROVIDER") or _satellite_settings().get("nwp_realtime_provider", "gfs_herbie")
    provider = provider.lower()
    if provider not in NWP_REALTIME_PROVIDERS:
        raise ValueError(f"Unknown nwp_realtime_provider {provider!r}; choose one of {sorted(NWP_REALTIME_PROVIDERS)}")
    return provider

def satellite_provider() -> str:
    """Return the configured provider; EUMETSAT is the interim default."""
    provider = os.getenv("ASTRA_SATELLITE_PROVIDER") or _satellite_settings().get("satellite_provider", "eumetsat_iodc")
    provider = provider.lower()
    if provider not in SATELLITE_PROVIDERS:
        raise ValueError(f"Unknown satellite_provider {provider!r}; choose one of {sorted(SATELLITE_PROVIDERS)}")
    return "eumetsat_iodc" if provider == "eumetsat" else provider

def _satellite_endpoint(settings: dict, provider: str, mode: Mode) -> str | None:
    # New configuration nests provider-specific endpoints.  The MOSDAC
    # fallbacks preserve the original config.json scaffold unchanged.
    provider_settings = settings.get(provider, {})
    if provider == "mosdac":
        provider_settings = {**settings, **provider_settings}
    return provider_settings.get("zarr_url") or provider_settings.get("latest_url" if mode is Mode.realtime else "historical_url")

def _canonicalise_satellite_dataset(dataset: xr.Dataset, provider: str) -> xr.Dataset:
    """Map staged provider channels and coordinates to the immutable ASTRA contract."""
    aliases = {
        "ir1_brightness_temperature": ("IR_108", "IR108", "ir_108", "IR_10.8"),
        "tir1_brightness_temperature": ("IR_120", "IR120", "ir_120", "IR_12.0"),
        "wv_brightness_temperature": ("WV_073", "WV073", "wv_073", "WV_7.3"),
    }
    rename: dict[str, str] = {}
    for target, candidates in aliases.items():
        if target not in dataset:
            source = next((name for name in candidates if name in dataset), None)
            if source:
                rename[source] = target
    for source, target in (("lat", "latitude"), ("latitude", "latitude"), ("lon", "longitude"), ("longitude", "longitude")):
        if target not in dataset.coords and source in dataset.coords and source != target:
            rename[source] = target
    if rename:
        dataset = dataset.rename(rename)
    for variable in SATELLITE_CONTRACT.required_variables:
        if variable in dataset and dataset[variable].attrs.get("units") in {"K", "Kelvin", "kelvin"}:
            dataset[variable].attrs["units"] = "K"
    dataset.attrs = {**dataset.attrs, "source": f"{provider} satellite", "satellite_provider": provider}
    return dataset

class INSATAdapter(SourceAdapter):
    """MOSDAC/INSAT staged output using the fixed ASTRA satellite contract."""
    contract = SATELLITE_CONTRACT
    def sample(self):
        y, x = np.meshgrid(LATITUDES, LONGITUDES, indexing="ij"); cloud = 14*np.exp(-((y-24)**2+(x-83)**2)/20)
        return _grid({"ir1_brightness_temperature": (290-cloud,"K"), "tir1_brightness_temperature": (288-cloud*.8,"K"), "wv_brightness_temperature": (260-cloud*.5,"K")}, "MOSDAC INSAT sample")
    def production(self, mode):
        settings = _satellite_settings()
        endpoint = _satellite_endpoint(settings, "mosdac", mode)
        if not endpoint:
            raise RuntimeError("MOSDAC is selected but not set up: run scripts/ingest_mosdac.py to create staged stores, then configure mosdac.historical_url and mosdac.latest_url in ASTRA_SATELLITE_CONFIG.")
        return _canonicalise_satellite_dataset(
            _open_endpoint(endpoint, "MOSDAC INSAT-3D/3DR staged output"), "mosdac"
        )

class EUMETSATIODCAdapter(SourceAdapter):
    """Meteosat-9 IODC (45.5°E; Meteosat-8 historical) normalised to MOSDAC's contract."""
    contract = SATELLITE_CONTRACT
    def sample(self):
        y, x = np.meshgrid(LATITUDES, LONGITUDES, indexing="ij"); cloud = 13*np.exp(-((y-24)**2+(x-83)**2)/20)
        return _grid({"ir1_brightness_temperature": (291-cloud,"K"), "tir1_brightness_temperature": (289-cloud*.8,"K"), "wv_brightness_temperature": (261-cloud*.5,"K")}, "EUMETSAT Meteosat-9 IODC sample")
    def production(self, mode):
        settings = _satellite_settings()
        endpoint = _satellite_endpoint(settings, "eumetsat_iodc", mode)
        label = "EUMETSAT Meteosat-9 IODC (45.5E; SEVIRI IR_108/IR_120/WV_073)"
        return _canonicalise_satellite_dataset(_open_endpoint(endpoint, label), "eumetsat_iodc")

class LightningAdapter(SourceAdapter):
    contract = DatasetContract(name="synthetic_lightning", representation="point", required_variables={"lightning_proxy": "strikes 30min-1"}, is_synthetic=True)
    def sample(self):
        points = np.arange(12); lat=np.linspace(7,37,12); lon=np.linspace(69,97,12)
        vals=np.stack([np.maximum(0, 10-abs(lat-25))* (1+t*.1) for t in range(len(TIMES))])
        return xr.Dataset({"lightning_proxy": (("time","point"),vals,{"units":"strikes 30min-1"})},coords={"time":TIMES,"point":points,"latitude":("point",lat),"longitude":("point",lon)},attrs={"is_synthetic":True,"formula":"deterministic spatial-temporal sample fixture; not CAPE × precipitation_rate"})

class GroundStationAdapter(SourceAdapter):
    """Meteostat observations assigned to the nearest supported ASTRA grid cell.

    Meteostat is station data, not a gridded analysis.  We deliberately leave
    cells farther than ``ASTRA_METEOSTAT_MAX_DISTANCE_KM`` as NaN instead of
    extrapolating weather across India.  The accompanying ``station_available``
    field is the per-cell coverage flag consumed by status/reporting code.
    """
    contract = DatasetContract(name="ground_stations", representation="grid", required_variables={
        "temperature_2m":"K", "relative_humidity":"%", "surface_pressure":"Pa",
        "wind_speed_10m":"m s-1", "rainfall_rate":"mm hr-1", "station_available":"1",
    })
    def sample(self):
        # CI and the zero-credential demo use this explicit synthetic fixture;
        # production never falls back to it.
        y, x = np.meshgrid(LATITUDES, LONGITUDES, indexing="ij")
        available = (((y - 22) ** 2 + (x - 78) ** 2) < 1).astype(float)
        values = {"temperature_2m": (np.full_like(y, 300.), "K"),
                  "relative_humidity": (np.full_like(y, 70.), "%"),
                  "surface_pressure": (np.full_like(y, 100000.), "Pa"),
                  "wind_speed_10m": (np.full_like(y, 5.), "m s-1"),
                  "rainfall_rate": (np.full_like(y, 3.), "mm hr-1"),
                  "station_available": (available, "1")}
        dataset = _grid(values, "Meteostat CI fixture")
        for name in dataset.data_vars:
            if name != "station_available": dataset[name] = dataset[name].where(dataset.station_available > 0)
        dataset.attrs.update({"provider": "meteostat", "is_synthetic": True,
                              "source_status": {"provider": "meteostat", "coverage_state": "degraded",
                                                "reason": "synthetic CI/sample fixture; not station observations"}})
        return dataset

    def production(self, mode: Mode):
        try:
            from meteostat import Stations, Hourly
        except ImportError as exc:
            raise RuntimeError("Meteostat ground stations require `pip install meteostat`.") from exc

        start, end = self._period(mode)
        stations = self._discover_stations(Stations)
        # Network failures at individual stations reduce coverage; they must
        # not turn into a fabricated value or abort all usable stations.
        def fetch_station(station_id):
            try:
                frame = Hourly(station_id, start, end).fetch()
                return str(station_id), frame if not frame.empty else None
            except Exception:
                return str(station_id), None
        workers = max(1, int(os.getenv("ASTRA_METEOSTAT_WORKERS", "8")))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            fetched = executor.map(fetch_station, stations.index)
            observations = {station_id: frame for station_id, frame in fetched if frame is not None}
        return self._to_grid(stations, observations, start, end)

    @staticmethod
    def _period(mode: Mode) -> tuple[datetime, datetime]:
        if mode is Mode.historical:
            start_text, end_text = os.getenv("ASTRA_METEOSTAT_START"), os.getenv("ASTRA_METEOSTAT_END")
            if not start_text or not end_text:
                raise RuntimeError("Historical Meteostat runs require ASTRA_METEOSTAT_START and ASTRA_METEOSTAT_END (ISO-8601 UTC).")
            start, end = datetime.fromisoformat(start_text.replace("Z", "+00:00")), datetime.fromisoformat(end_text.replace("Z", "+00:00"))
        else:
            end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
            start = end - timedelta(hours=4)
        # Meteostat 1.x indexes its hourly archive with timezone-naive UTC
        # timestamps.  Normalise configured offsets before handing them over.
        if start.tzinfo is not None: start = start.astimezone(timezone.utc).replace(tzinfo=None)
        if end.tzinfo is not None: end = end.astimezone(timezone.utc).replace(tzinfo=None)
        if end < start: raise ValueError("ASTRA_METEOSTAT_END must not precede ASTRA_METEOSTAT_START")
        return start, end

    @staticmethod
    def _anchors() -> list[tuple[float, float]]:
        # A coarse national sample plus major cities keeps station discovery
        # bounded while explicitly testing the requested pan-India locations.
        step = float(os.getenv("ASTRA_METEOSTAT_ANCHOR_STEP_DEGREES", "2"))
        if step <= 0: raise ValueError("ASTRA_METEOSTAT_ANCHOR_STEP_DEGREES must be positive")
        anchors = [(float(lat), float(lon)) for lat in np.arange(6, 38.01, step) for lon in np.arange(68, 98.01, step)]
        anchors += [(19.076, 72.878), (28.614, 77.209), (22.572, 88.364), (13.083, 80.270)] # Mumbai, Delhi, Kolkata, Chennai
        return anchors

    def _discover_stations(self, Stations):
        frames = []
        for latitude, longitude in self._anchors():
            found = Stations().nearby(latitude, longitude).fetch(1)
            if not found.empty: frames.append(found)
        if not frames:
            # Preserve a valid full grid with all cells explicitly unavailable.
            import pandas as pd
            return pd.DataFrame(columns=["latitude", "longitude"])
        import pandas as pd
        stations = pd.concat(frames)
        return stations[~stations.index.duplicated(keep="first")].dropna(subset=["latitude", "longitude"])

    @staticmethod
    def _to_grid(stations, observations: dict[str, object], start: datetime, end: datetime) -> xr.Dataset:
        times = np.arange(np.datetime64(start.replace(tzinfo=None), "h"), np.datetime64(end.replace(tzinfo=None), "h") + np.timedelta64(1, "h"), np.timedelta64(1, "h"))
        shape = (len(times), len(LATITUDES), len(LONGITUDES))
        names = {"temperature_2m": ("temp", 1., 273.15), "relative_humidity": ("rhum", 1., 0.),
                 "surface_pressure": ("pres", 100., 0.), "wind_speed_10m": ("wspd", 1 / 3.6, 0.), "rainfall_rate": ("prcp", 1., 0.)}
        values = {name: np.full(shape, np.nan) for name in names}
        available = np.zeros(shape, dtype=float)
        max_distance = float(os.getenv("ASTRA_METEOSTAT_MAX_DISTANCE_KM", "75"))
        usable = stations.loc[[index for index in stations.index if str(index) in observations]] if len(stations.index) else stations
        if len(usable.index):
            lat, lon = np.meshgrid(LATITUDES, LONGITUDES, indexing="ij")
            # Equirectangular distance is sufficiently accurate at the explicit
            # coverage cutoff, and avoids assigning any remote station.
            dlat = (lat[..., None] - usable.latitude.to_numpy()) * 111.32
            dlon = (lon[..., None] - usable.longitude.to_numpy()) * 111.32 * np.cos(np.deg2rad(lat[..., None]))
            nearest = np.sqrt(dlat ** 2 + dlon ** 2).argmin(axis=2)
            distance = np.take_along_axis(np.sqrt(dlat ** 2 + dlon ** 2), nearest[..., None], axis=2)[..., 0]
            covered = distance <= max_distance
            for station_pos, station_id in enumerate(usable.index):
                mask = covered & (nearest == station_pos)
                frame = observations[str(station_id)]
                for t, timestamp in enumerate(times):
                    row = frame.loc[frame.index == timestamp]
                    if row.empty: continue
                    for output, (column, factor, offset) in names.items():
                        if column not in row: continue
                        try:
                            observation = float(row.iloc[0][column])
                        except (TypeError, ValueError):
                            continue  # pandas.NA and absent station fields stay missing
                        if np.isfinite(observation): values[output][t][mask] = observation * factor + offset
            available = np.isfinite(values["temperature_2m"]).astype(float)
        data = {name: (("time", "latitude", "longitude"), array, {"units": unit}) for name, array, unit in [
            ("temperature_2m", values["temperature_2m"], "K"), ("relative_humidity", values["relative_humidity"], "%"),
            ("surface_pressure", values["surface_pressure"], "Pa"), ("wind_speed_10m", values["wind_speed_10m"], "m s-1"),
            ("rainfall_rate", values["rainfall_rate"], "mm hr-1"), ("station_available", available, "1")]
        }
        coverage = [float(frame.mean()) for frame in available]
        state = "complete" if min(coverage, default=0.) >= .8 else "degraded"
        return xr.Dataset(data, coords={"time": times, "latitude": LATITUDES, "longitude": LONGITUDES}, attrs={
            "provider": "meteostat", "is_synthetic": False, "station_count": int(len(usable.index)),
            "max_station_distance_km": max_distance,
            "source_status": {"provider": "meteostat", "coverage_state": state,
                              "valid_grid_fraction_by_frame": coverage,
                              "reason": "Meteostat station density is sparse for 0.25 degree use" if state == "degraded" else None},
        })

class NWPAdapter(SourceAdapter):
    contract = DatasetContract(name="nwp", representation="grid", required_variables={"cape":"J kg-1","cin":"J kg-1","temperature_1000":"K","humidity_1000":"%","u_1000":"m s-1","v_1000":"m s-1","u_500":"m s-1","v_500":"m s-1"})
    def sample(self):
        y,x=np.meshgrid(LATITUDES,LONGITUDES,indexing="ij"); cape=300+1500*np.exp(-((y-25)**2+(x-82)**2)/25)
        return _grid({"cape":(cape,"J kg-1"),"cin":(-cape*.08,"J kg-1"),"temperature_1000":(np.full_like(cape,300),"K"),"humidity_1000":(np.full_like(cape,75),"%"),"u_1000":(np.full_like(cape,4),"m s-1"),"v_1000":(np.full_like(cape,2),"m s-1"),"u_500":(np.full_like(cape,18),"m s-1"),"v_500":(np.full_like(cape,8),"m s-1")},"ERA5/GFS sample")
    def production(self, mode):
        if mode is Mode.historical:
            return _open_endpoint(os.getenv("ASTRA_ERA5_ZARR_URL"), "ERA5 via cdsapi")
        provider = nwp_realtime_provider()
        if provider == "open_meteo":
            raise RuntimeError("Open-Meteo is limited to small point queries and cannot provide the full pan-India NWP grid. Set ASTRA_NWP_REALTIME_PROVIDER=gfs_herbie.")
        return self._gfs_herbie_realtime()

    def _gfs_herbie_realtime(self) -> xr.Dataset:
        """Subset GFS 0.25-degree GRIB fields through Herbie for the ASTRA grid."""
        try:
            from herbie import Herbie
        except ImportError as exc:
            raise RuntimeError("GFS realtime NWP requires `pip install herbie-data`.") from exc

        forecast_hours = int(os.getenv("ASTRA_GFS_FORECAST_HOURS", "5"))
        lookback_cycles = int(os.getenv("ASTRA_GFS_LOOKBACK_CYCLES", "4"))
        if forecast_hours < 1 or lookback_cycles < 1:
            raise ValueError("ASTRA_GFS_FORECAST_HOURS and ASTRA_GFS_LOOKBACK_CYCLES must be positive")
        product = os.getenv("ASTRA_GFS_PRODUCT", "pgrb2.0p25")
        cache_directory = Path(os.getenv("ASTRA_HERBIE_CACHE_DIR", "var/herbie"))
        cache_directory.mkdir(parents=True, exist_ok=True)
        # Herbie applies this wgrib2-style search to the remote index, so only
        # CAPE:surface and the requested 1000/500 mb thermodynamics/winds are
        # downloaded rather than a complete global GRIB file.
        search = r":(?:CAPE:surface|(?:TMP|RH|UGRD|VGRD):(?:1000|500) mb:)"
        now = datetime.now(timezone.utc).replace(tzinfo=None, minute=0, second=0, microsecond=0)
        latest_cycle = now.replace(hour=(now.hour // 6) * 6)
        errors: list[str] = []
        for cycle_offset in range(lookback_cycles):
            cycle = latest_cycle - timedelta(hours=6 * cycle_offset)
            try:
                frames = []
                for forecast_hour in range(forecast_hours):
                    herbie = Herbie(cycle, model="gfs", product=product, fxx=forecast_hour,
                                    priority=["aws", "nomads", "google"], save_dir=cache_directory, verbose=False)
                    selected = herbie.xarray(search=search, remove_grib=True)
                    frames.append(self._gfs_frame(selected, cycle + timedelta(hours=forecast_hour)))
                result = xr.concat(frames, dim="time")
                result.attrs.update({"source": "NOAA GFS via Herbie", "provider": "gfs_herbie",
                                     "model": "gfs", "product": product, "run_time_utc": cycle.isoformat() + "Z",
                                     "forecast_hours": forecast_hours, "grib_search": search,
                                     "cin_status": "unavailable: CAPE:surface was requested as scoped"})
                return result
            except Exception as exc:
                errors.append(f"{cycle.isoformat()}Z: {exc}")
        raise RuntimeError("No complete recent GFS cycle was available through Herbie. " + " | ".join(errors))

    def _gfs_frame(self, selected, valid_time: datetime) -> xr.Dataset:
        """Normalise Herbie/cfgrib's surface and isobaric datasets to ASTRA."""
        parts = selected if isinstance(selected, (list, tuple)) else [selected]

        def variable(short_names: set[str], pressure_hpa: int | None = None) -> xr.DataArray:
            for part in parts:
                for name, data in part.data_vars.items():
                    short_name = str(data.attrs.get("GRIB_shortName", name)).lower()
                    if short_name not in short_names:
                        continue
                    if pressure_hpa is not None:
                        level = next((coord for coord in data.coords if "isobaric" in coord.lower()), None)
                        if level is None:
                            continue
                        level_values = np.asarray(data[level].values)
                        requested = pressure_hpa if np.any(level_values == pressure_hpa) else pressure_hpa * 100
                        if not np.any(level_values == requested):
                            continue
                        # Drop the scalar level coordinate: the final ASTRA
                        # variables intentionally live at different levels.
                        data = data.sel({level: requested}, drop=True)
                    return data.squeeze(drop=True)
            requested = "/".join(sorted(short_names)) + (f" at {pressure_hpa} mb" if pressure_hpa else "")
            raise RuntimeError(f"Herbie GFS subset did not contain {requested}")

        data = {
            "cape": variable({"cape"}),
            "temperature_1000": variable({"t", "tmp"}, 1000),
            "humidity_1000": variable({"r", "rh"}, 1000),
            "u_1000": variable({"u", "ugrd"}, 1000),
            "v_1000": variable({"v", "vgrd"}, 1000),
            "u_500": variable({"u", "ugrd"}, 500),
            "v_500": variable({"v", "vgrd"}, 500),
        }
        # CIN is absent by design from this scoped GFS selection; preserve the
        # immutable field and make its absence explicit instead of fabricating it.
        reference = data["cape"]
        data["cin"] = xr.full_like(reference, np.nan, dtype=float)
        frame = xr.Dataset(data).squeeze(drop=True)
        for source, target in (("lat", "latitude"), ("lon", "longitude")):
            if target not in frame.coords and source in frame.coords:
                frame = frame.rename({source: target})
        if "latitude" not in frame.dims or "longitude" not in frame.dims:
            raise RuntimeError("GFS subset is not a rectilinear latitude/longitude grid required for pan-India staging")
        frame = frame.interp(latitude=LATITUDES, longitude=LONGITUDES, method="linear")
        for name, unit in self.contract.required_variables.items():
            frame[name].attrs["units"] = unit
        return frame.expand_dims(time=[np.datetime64(valid_time, "ns")])

    def _open_meteo_realtime(self) -> xr.Dataset:
        """Fetch the fixed ASTRA grid from Open-Meteo's multi-location API.

        The public API accepts comma-separated latitude/longitude lists and
        returns one hourly structure per location.  Batching avoids a request
        per cell while keeping URLs well below ordinary proxy limits.  It is
        intentionally a point pull: Open-Meteo selects/interpolates its model
        grid at each requested ASTRA grid coordinate.
        """
        import requests

        batch_size = int(os.getenv("ASTRA_OPEN_METEO_BATCH_SIZE", "100"))
        workers = int(os.getenv("ASTRA_OPEN_METEO_WORKERS", "4"))
        timeout = float(os.getenv("ASTRA_OPEN_METEO_TIMEOUT_SECONDS", "60"))
        forecast_hours = int(os.getenv("ASTRA_OPEN_METEO_FORECAST_HOURS", "5"))
        if batch_size < 1 or workers < 1 or timeout <= 0 or forecast_hours < 1:
            raise ValueError("Open-Meteo batch size, workers, timeout and forecast hours must be positive")

        # Open-Meteo supplies scalar speed/direction, while the locked NWP
        # contract is vector wind at 1000 and 500 hPa for bulk shear.
        hourly = [
            "cape", "temperature_2m", "relative_humidity_2m",
            "wind_speed_1000hPa", "wind_direction_1000hPa",
            "wind_speed_500hPa", "wind_direction_500hPa",
        ]
        lat, lon = np.meshgrid(LATITUDES, LONGITUDES, indexing="ij")
        points = list(zip(lat.ravel(), lon.ravel()))
        batches = [points[offset:offset + batch_size] for offset in range(0, len(points), batch_size)]

        def fetch(batch):
            params = {
                "latitude": ",".join(f"{value:.2f}" for value, _ in batch),
                "longitude": ",".join(f"{value:.2f}" for _, value in batch),
                "hourly": ",".join(hourly), "forecast_hours": forecast_hours,
                "timezone": "GMT", "temperature_unit": "celsius", "wind_speed_unit": "ms",
            }
            response = requests.get(OPEN_METEO_FORECAST_URL, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            locations = payload if isinstance(payload, list) else [payload]
            if len(locations) != len(batch):
                raise RuntimeError(f"Open-Meteo returned {len(locations)} locations for a batch of {len(batch)}")
            return batch, locations

        started = perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as executor:
            responses = list(executor.map(fetch, batches))
        elapsed = perf_counter() - started

        times = None
        shape = (forecast_hours, len(LATITUDES), len(LONGITUDES))
        values = {name: np.full(shape, np.nan) for name in self.contract.required_variables}
        for batch, locations in responses:
            for (point_lat, point_lon), location in zip(batch, locations):
                hourly_data = location.get("hourly", {})
                location_times = np.asarray(hourly_data.get("time", []), dtype="datetime64[ns]")
                if len(location_times) != forecast_hours:
                    raise RuntimeError(f"Open-Meteo returned {len(location_times)} hourly frames; expected {forecast_hours}")
                if times is None:
                    times = location_times
                elif not np.array_equal(times, location_times):
                    raise RuntimeError("Open-Meteo batches returned inconsistent hourly timestamps")
                iy = int(round((point_lat - LATITUDES[0]) / RESOLUTION))
                ix = int(round((point_lon - LONGITUDES[0]) / RESOLUTION))
                def field(name):
                    result = np.asarray(hourly_data.get(name, []), dtype=float)
                    if len(result) != forecast_hours:
                        raise RuntimeError(f"Open-Meteo hourly field {name!r} has {len(result)} frames; expected {forecast_hours}")
                    return result
                values["cape"][:, iy, ix] = field("cape")
                # The immutable ERA5-shaped interface calls these 1000 hPa.
                # Open-Meteo's requested 2 m thermodynamics are the explicit
                # near-surface proxy used in real-time mode.
                values["temperature_1000"][:, iy, ix] = field("temperature_2m") + 273.15
                values["humidity_1000"][:, iy, ix] = field("relative_humidity_2m")
                for level, output in (("1000", "u_1000"), ("500", "u_500")):
                    speed = field(f"wind_speed_{level}hPa")
                    # Meteorological direction is where wind comes FROM.
                    direction = np.deg2rad(field(f"wind_direction_{level}hPa"))
                    values[output][:, iy, ix] = -speed * np.sin(direction)
                    values[output.replace("u_", "v_")][:, iy, ix] = -speed * np.cos(direction)
                # Open-Meteo does not expose CIN in this endpoint.  Retain the
                # schema field explicitly as unavailable rather than inventing it.

        data = {
            name: (("time", "latitude", "longitude"), values[name], {"units": unit})
            for name, unit in self.contract.required_variables.items()
        }
        dataset = xr.Dataset(
            data,
            coords={"time": times, "latitude": LATITUDES, "longitude": LONGITUDES},
            attrs={"source": "Open-Meteo forecast", "provider": "open_meteo", "mode": "realtime",
                   "is_synthetic": False, "request_count": len(batches), "request_seconds": elapsed,
                   "point_count": len(points), "batch_size": batch_size,
                   "thermodynamics": "temperature_2m/relative_humidity_2m mapped to ERA5-shaped 1000 hPa near-surface fields; CIN unavailable"},
        )
        return dataset

def _open_endpoint(endpoint, label):
    if not endpoint: raise RuntimeError(f"{label} endpoint missing. Configure the relevant ASTRA_*_ZARR_URL.")
    return xr.open_zarr(endpoint, chunks="auto") if endpoint.endswith(".zarr") else xr.open_dataset(endpoint, chunks="auto")

def default_adapters():
    satellite = EUMETSATIODCAdapter() if satellite_provider() == "eumetsat_iodc" else INSATAdapter()
    return [GPMAdapter(), satellite, LightningAdapter(), GroundStationAdapter(), NWPAdapter()]
