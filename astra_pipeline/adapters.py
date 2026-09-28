"""Pluggable source adapters. Sample mode is intentionally self-contained."""
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
import json, os
import numpy as np
import xarray as xr
from .contracts import Mode, SourceMetadata, DatasetContract
from .domain import LATITUDES, LONGITUDES

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
SATELLITE_PROVIDERS = {"eumetsat_iodc", "mosdac"}

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
    path = Path(os.getenv("ASTRA_SATELLITE_CONFIG", os.getenv("ASTRA_MOSDAC_CONFIG", "config.json")))
    return json.loads(path.read_text()) if path.exists() else {}

def satellite_provider() -> str:
    """Return the configured provider; EUMETSAT is the interim default."""
    provider = os.getenv("ASTRA_SATELLITE_PROVIDER") or _satellite_settings().get("satellite_provider", "eumetsat_iodc")
    provider = provider.lower()
    if provider not in SATELLITE_PROVIDERS:
        raise ValueError(f"Unknown satellite_provider {provider!r}; choose one of {sorted(SATELLITE_PROVIDERS)}")
    return provider

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
    """Existing MOSDAC/INSAT scaffold, retained for the eventual approved feed."""
    contract = SATELLITE_CONTRACT
    def sample(self):
        y, x = np.meshgrid(LATITUDES, LONGITUDES, indexing="ij"); cloud = 14*np.exp(-((y-24)**2+(x-83)**2)/20)
        return _grid({"ir1_brightness_temperature": (290-cloud,"K"), "tir1_brightness_temperature": (288-cloud*.8,"K"), "wv_brightness_temperature": (260-cloud*.5,"K")}, "MOSDAC INSAT sample")
    def production(self, mode):
        settings = _satellite_settings()
        endpoint = _satellite_endpoint(settings, "mosdac", mode)
        return _canonicalise_satellite_dataset(
            _open_endpoint(endpoint, "MOSDAC INSAT-3D/3DR (latest=True for realtime)"), "mosdac"
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
        return xr.Dataset({"lightning_proxy": (("time","point"),vals,{"units":"strikes 30min-1"})},coords={"time":TIMES,"point":points,"latitude":("point",lat),"longitude":("point",lon)},attrs={"is_synthetic":True,"formula":"CAPE x precipitation_rate"})

class GroundStationAdapter(SourceAdapter):
    contract = DatasetContract(name="ground_stations_pending", representation="point", required_variables={"temperature_2m":"K","relative_humidity":"%","surface_pressure":"Pa","wind_speed_10m":"m s-1","rainfall_rate":"mm hr-1"}, pending_source=True)
    def sample(self):
        p=np.arange(10); lat=np.linspace(6.1,37.9,10); lon=np.linspace(68.1,97.9,10); data={}
        for name,unit,value in [("temperature_2m","K",300),("relative_humidity","%",70),("surface_pressure","Pa",100000),("wind_speed_10m","m s-1",5),("rainfall_rate","mm hr-1",3)]: data[name]=(("time","point"),np.full((len(TIMES),len(p)),value),{"units":unit})
        return xr.Dataset(data,coords={"time":TIMES,"point":p,"latitude":("point",lat),"longitude":("point",lon)},attrs={"pending_real_source":True})

class NWPAdapter(SourceAdapter):
    contract = DatasetContract(name="nwp", representation="grid", required_variables={"cape":"J kg-1","cin":"J kg-1","temperature_1000":"K","humidity_1000":"%","u_1000":"m s-1","v_1000":"m s-1","u_500":"m s-1","v_500":"m s-1"})
    def sample(self):
        y,x=np.meshgrid(LATITUDES,LONGITUDES,indexing="ij"); cape=300+1500*np.exp(-((y-25)**2+(x-82)**2)/25)
        return _grid({"cape":(cape,"J kg-1"),"cin":(-cape*.08,"J kg-1"),"temperature_1000":(np.full_like(cape,300),"K"),"humidity_1000":(np.full_like(cape,75),"%"),"u_1000":(np.full_like(cape,4),"m s-1"),"v_1000":(np.full_like(cape,2),"m s-1"),"u_500":(np.full_like(cape,18),"m s-1"),"v_500":(np.full_like(cape,8),"m s-1")},"ERA5/GFS sample")
    def production(self, mode):
        endpoint=os.getenv("ASTRA_ERA5_ZARR_URL" if mode is Mode.historical else "ASTRA_GFS_ZARR_URL")
        return _open_endpoint(endpoint, "ERA5 via cdsapi" if mode is Mode.historical else "GFS via Herbie/Open-Meteo")

def _open_endpoint(endpoint, label):
    if not endpoint: raise RuntimeError(f"{label} endpoint missing. Configure the relevant ASTRA_*_ZARR_URL.")
    return xr.open_zarr(endpoint, chunks="auto") if endpoint.endswith(".zarr") else xr.open_dataset(endpoint, chunks="auto")

def default_adapters():
    satellite = EUMETSATIODCAdapter() if satellite_provider() == "eumetsat_iodc" else INSATAdapter()
    return [GPMAdapter(), satellite, LightningAdapter(), GroundStationAdapter(), NWPAdapter()]
