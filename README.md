# ASTRA pan-India data pipeline

This package implements the PRD data milestone for the whole locked ASTRA domain: **6–38°N, 68–98°E**, on an inclusive **0.25°** grid (129 × 121 cells). It is separate from the existing dashboard assets.

## Run the zero-credential demo

```powershell
python -m pip install -r requirements.txt
python scripts/run_sample.py
python -m pytest
```

The `sample` adapters generate a small deterministic five-timestep data cube. It exercises GPM-like rain, the three INSAT channels, a CAPE × rainfall lightning proxy, a CI-only Meteostat station fixture, and ERA5/GFS-like model fields. It deliberately covers the entire domain and emits JSON schemas in `schemas/`.

## Historical Open-Meteo atmospheric context

`data/atmospheric/open_meteo_india_5_locations.csv` is a five-location (Mumbai, Delhi, Kolkata, Chennai, and Bhopal) **hourly Open-Meteo historical/model-derived atmospheric archive**. It is not live data, direct sensor observation, a forecast feed, or a lightning dataset. The raw two-section provider export is retained unchanged; `astra_pipeline/atmospheric.py` reads it into a separate normalised point representation while preserving raw column names and missing values as `NaN`.

The loader preserves location ID, latitude, longitude, and converts provider-local timestamps to UTC. It validates required fields, valid coordinates, unique location IDs, parseable timestamps, duplicate location/timestamp records, missing-value percentages, and records after the validation time. It does not interpolate, forward-fill, or manufacture future values. Normalised fields cover basic thermodynamics, pressure, precipitation, cloud, wind, visibility, supported pressure-level temperature/RH/wind-speed fields, plus supported derived temperature differences/lapse-rate proxies, moisture gradients, and 10 m wind vectors. This export has no pressure-level wind directions, so vertical vector wind shear is intentionally absent.

It is intentionally **not** a `default_adapters()` source: five points cannot meet ASTRA's fixed pan-India 0.25° grid contract without unsafe interpolation. It is reusable standalone ingestion for later grid archives, and can be joined as context only after a downstream design explicitly handles sparse points. It must never be used to fabricate CAPE/CIN, radar, satellite, or lightning observations; NRSC/ISRO lightning remains a separate future source.

Preview the archive and its provenance/completeness with:

```powershell
python scripts/preview_open_meteo_atmospheric.py
```

## Historical NASA ISS-LIS lightning observations

`astra_pipeline/iss_lis.py` ingests **NASA ISS-LIS V3.0 historical satellite lightning observations** for training, validation, climatology/context, feature engineering, and future-label generation. It is observed (`observed: true`), historical (`forecast: false`), and non-synthetic. It is not an operational live lightning feed and does not replace the explicitly labelled synthetic CI fixture until a training artifact is built from processed observations.

The canonical input is NetCDF. A representative V3.0 file contains event, group, flash, orbit, and 0.5° viewtime records; the event pipeline uses actual `lightning_event_TAI93_time`, latitude/longitude, addresses, radiance/footprint, alert, clustering, and noise fields. Event-to-flash IDs are resolved through the source group-parent relationship. There is no reliable cloud-to-ground/cloud-to-cloud type field in this schema, so ASTRA does not invent one. HDF4 copies are not processed alongside paired NetCDF files, preventing duplicate observations.

Raw ISS-LIS files belong outside Git (for example `data/raw/iss_lis/`, which is ignored). The streaming command processes one granule at a time, writes Parquet event partitions, records each result in `processed_files.csv`, and produces configurable grid/temporal aggregates plus causally safe historical lightning features. The current India filter is explicitly a configurable **bounding box**, not an India polygon: west 68.1, south 6.7, east 97.5, north 37.1. Replace it with an official boundary before treating the filter as exact India coverage.

```powershell
# First validate a small subset.
python scripts/ingest_iss_lis.py --input-dir C:\path\to\iss_lis --output-dir data\processed\iss_lis --limit 10

# Continue after a successful review; successful manifest rows are not repeated.
python scripts/ingest_iss_lis.py --input-dir C:\path\to\iss_lis --output-dir data\processed\iss_lis --resume --resolution 0.25 --interval 5min
```

The generated `lightning_features_*` uses only observations at or before each bucket timestamp (5/10/30/60-minute rolling counts, growth, and acceleration). A future target, such as activity in T→T+30 minutes, must be created in a separate join after the prediction-time feature row is fixed; this prevents target leakage. Atmospheric Open-Meteo data can only be aligned explicitly by UTC time and grid/location, accounting for its hourly five-point coverage—it must never be blindly merged with the higher-frequency satellite observations.

## Contracts and pipeline

`astra_pipeline/contracts.py` contains Pydantic metadata contracts and `DatasetContract` validation for every xarray payload. `SourceMetadata.model_json_schema()` and `FusedOutputMetadata.model_json_schema()` produce the source/fused JSON Schemas; the demo also writes one fixed JSON Schema per source in `schemas/`. Before fusion, every adapter is schema-validated. Processing is quality check → 0.25° regrid → 30-minute nearest-bucket alignment → point binning → derived 1000–500 mb bulk shear → lazy normalisation → four-frame last-hour sequences.

Gridded production sources open Zarr with `chunks="auto"`; reductions remain xarray/Dask lazy. Point batches are explicitly binned per observation interval, avoiding a seasonal grid materialisation.

## Credentials and production modes

| Adapter | Historical | Real-time | Setup |
|---|---|---|---|
| GPM IMERG | `GPM_3IMERGHH` Final | `GPM_3IMERGHHE` Early (~4 h) | NASA Earthdata `~/.netrc`; set `ASTRA_GPM_ZARR_URL` |
| Satellite (fixed `insat_3d_3dr` contract) | EUMETSAT Meteosat-9 IODC archive (45.5°E; Meteosat-8 historical) | EUMETSAT IODC latest feed | `config.json` (or `ASTRA_SATELLITE_CONFIG`): `satellite_provider: eumetsat`, plus staged `historical_url`/`latest_url` or `zarr_url` |
| Satellite alternate: INSAT-3DR | MOSDAC L1C ASIA_MER archive | MOSDAC L1C ASIA_MER latest feed | Set `satellite_provider` to `mosdac`; credentials are read only from the external file named by `ASTRA_MOSDAC_CONFIG` |
| Lightning | synthetic CAPE × rain proxy | synthetic CAPE × rain proxy | none; contract has `is_synthetic: true` |
| Ground stations | Meteostat hourly station archive | Meteostat latest available hourly station data | `pip install meteostat`; station cache stays at Meteostat's default `~/.meteostat/cache` (outside this repository) |
| NWP | ERA5 / cdsapi target | NOAA GFS 0.25° via Herbie | Install `herbie-data`; `gfs_herbie` is the default. Open-Meteo is restricted to small point fallback queries. |

Use `PreprocessingPipeline().run("historical")` or `.run("realtime")` once endpoints are staged. Set `satellite_provider` to `eumetsat` or `mosdac`; an unconfigured choice fails before preprocessing. For MOSDAC, run `scripts/ingest_mosdac.py` manually on a tiny range: it searches/downloads `3RIMG_L1C_ASIA_MER`, sends the configured 68–98°E / 6–38°N bounding box and a three-scene cap, enforces a persistent 5,000 download-requests-per-day ceiling, and prints file size plus download/decode timings. The staged output maps MOSDAC TIR-1, TIR-2, and WV to `ir1_brightness_temperature`, `tir1_brightness_temperature`, and `wv_brightness_temperature` in Kelvin. The credentials file is never copied into shared configuration. The EUMETSAT adapter continues to normalise SEVIRI `IR_108`, `IR_120`, and `WV_073` to the same contract.

### GFS/Herbie real-time NWP smoke test

Real-time NWP uses Herbie to subset NOAA GFS `pgrb2.0p25` at the source, requesting `CAPE:surface` and `TMP`, `RH`, `UGRD`, and `VGRD` at 1000 and 500 mb. It stages the fixed 129 × 121 pan-India grid under the existing ERA5-shaped NWP contract, with real GFS temperature/RH/wind values and an explicit `NaN` CIN field because CIN is not part of the scoped GRIB selection. Herbie checks recent six-hourly cycles and falls back to a complete older cycle when the newest one is not published yet.

CI mocks Herbie. To perform the intentional live pull, run:

```powershell
python scripts/smoke_gfs_herbie_india.py --live
```

Open-Meteo is no longer permitted as the full-grid provider; it is retained only for small point-query fallback work.

### Live EUMETSAT IODC satellite ingestion

The live IODC satellite is **Meteosat-9 at 45.5°E**; Meteosat-8 at 41.5°E is historical only. ASTRA downloads EUMETSAT collection `EO:EUM:DAT:MSG:HRSEVIRI-IODC` (Level 1.5 SEVIRI), directly decodes its native scene files with Satpy, and stages calibrated `IR_108`, `IR_120`, and `WV_073` brightness temperatures on the fixed pan-India grid.

Request EUMETSAT Data Store access under the applicable **Personal/Education/Research** licence scope, then initialise the local EUMDAC credential store:

```powershell
python -m pip install -r requirements.txt
eumdac --set-credentials
```

This writes credentials only to `~/.eumdac/credentials` (or `EUMDAC_CONFIG_DIR/credentials`). Never copy the consumer key, secret, or access tokens into `config.json`, `.env`, source code, CI variables, or logs. The ingest command fails clearly when that local store is absent. Run a small archive smoke test first; it prints only scene ID, byte size, download seconds, decode/subset seconds, and peak MiB:

```powershell
python scripts/ingest_eumetsat_iodc.py --start 2026-09-01T00:00:00Z --end 2026-09-01T01:00:00Z
```

It writes `historical.zarr` and a four-frame-or-more `latest.zarr`, then atomically places their local paths in the EUMETSAT section of `config.json`. It aligns observed scenes to 30-minute buckets without temporal interpolation; a missing bucket remains NaN and produces `state: delayed` with `missing_buckets_utc` in satellite source status. MOSDAC is untouched and remains selectable with `"satellite_provider": "mosdac"`.

Satpy is pinned at `0.58.0`. On Windows, install it in the project virtual environment first; native geospatial wheels (`pyresample`, `pyproj`, and raster dependencies) may require a current 64-bit Python and pip. If wheel installation fails, use a Conda environment with conda-forge geospatial packages, then install the pinned requirements there. CI never invokes Satpy or EUMETSAT: it uses synthetic reader fixtures.

### Ground stations: Meteostat coverage and licence

`GroundStationAdapter` uses `meteostat.Stations().nearby()` over a bounded 2° national anchor sample (including Mumbai, Delhi, Kolkata and Chennai), deduplicates the real stations found, and retrieves their records with `meteostat.Hourly`. It converts Meteostat's Celsius/hPa/km/h fields to the pipeline's K/Pa/m s-1 contract and nearest-neighbour assigns a station only within `ASTRA_METEOSTAT_MAX_DISTANCE_KM` (75 km by default). Cells beyond that radius, or cells/times with no observation, are **NaN** and have `station_available = 0`; they are reported as degraded rather than invented. Production output has `provider: "meteostat"` and `is_synthetic: false`.

This is intentionally not an interpolation product. India may have insufficient Meteostat station density for a 0.25° grid; a production output is marked degraded whenever less than 80% of cells are supported, and its status records the coverage fraction and reason. A live 2026-09-29 probe using a coarse 4° discovery sample found 69 usable stations and only ~9.7% supported grid cells, so **Meteostat is currently too sparse to use as a standalone 0.25° pan-India source**. Do not treat it as nationally complete merely because its coordinates span the national grid. The sample adapter is a clearly marked synthetic CI fixture and is never used as a production fallback.

Meteostat data is licensed under **CC BY-NC 4.0**: this integration is for non-commercial use only. Keep Meteostat's default local cache (`~/.meteostat/cache`) outside the repository; do not symlink or copy it into this project.

Before a full-grid run, manually verify station coverage and hourly availability for the four major cities:

```powershell
python scripts/smoke_meteostat_india.py
```

For a historical period, set `ASTRA_METEOSTAT_START` and `ASTRA_METEOSTAT_END` to ISO-8601 UTC timestamps. Realtime uses the most recent five whole UTC hours. CI mocks the Meteostat client; it does not call the network.

Lightning remains synthetic and is always labelled as such. The test suite includes an explicit full-domain assertion and a failing narrow-adapter case so a regional feed cannot quietly reduce coverage.

## Phase 2 nowcasting baselines

`astra_pipeline/baselines.py` consumes only Phase 1's `atmospheric_state(feature="precipitation_rate")`. It supplies persistence and a dense Lucas–Kanade optical-flow extrapolation, then calculates POD, FAR, and CSI for 10, 20, 30, 40, 50 and 60 minutes on exact held-out observation times.

```powershell
python scripts/run_baseline.py --fused-zarr path/to/fused-test.zarr --test-start 2026-06-01T00:00
```

The current bundled ingestion demo has 30-minute timestamps, so it can honestly verify only T+30 and T+60; its other lead scores are `NaN`, never invented. A proper six-lead benchmark needs Phase 1 fused radar-proxy outputs/targets at 10-minute cadence (the evaluator deliberately requires exact timestamps). Since Phase 1 normalizes the fused field, `event_threshold` is a fixed z-score threshold (default `0.5`) and must be chosen on training data before reporting held-out scores.

## Phase 3 primary nowcasting model

`AstraNowcastNet` is a shared ConvLSTM encoder over four 10-minute fused frames (the last hour), with two six-channel probability heads: storm field and lightning. It uses focal BCE and a weighted positive-window sampler. Monte Carlo dropout produces per-cell/per-lead probability and agreement confidence. `tracking.py` detects connected storm components and links them with Hungarian centroid matching, reporting position, velocity, direction, and growing/decaying trend.

```powershell
python scripts/train_nowcast.py --train-zarr path/to/fused-2024.zarr --test-zarr path/to/fused-heldout.zarr --epochs 20
```

The training data must contain the requested Apr–Jun 2024 and Jul–Aug 2024 windows and have exact 10-minute timestamps plus `precipitation_rate` and `lightning_proxy` feature labels. The command refuses 30-minute tensors and incomplete lead targets. It evaluates POD/FAR/CSI for both heads at all leads, emits a confidence reliability dataset separately, and asserts the full 129×121 / 6–38°N / 68–98°E domain before window construction. Use the Phase 2 script on the same held-out Zarr period for the comparison baseline; no honest primary-vs-baseline numbers can be produced until that actual historical dataset is supplied.

## Deterministic risk assessment

`risk.py` turns Phase 3 tracks, probability, MC-dropout confidence, and gradient×input attribution into a **review-only** warning draft. It tiers severity, projects motion/ETA, intersects administrative boundaries and exposure geometry, and ranks storms by a 0–100 ASTRA Impact Index. Drafts are always marked `DRAFT_FOR_FORECASTER_REVIEW — NOT_DISPATCHED`.

```powershell
python scripts/fetch_infrastructure.py --spot-check-only
python scripts/fetch_infrastructure.py --output data/critical_infrastructure.geojson --boundaries-output data/administrative_boundaries.geojson
$env:DATABASE_URL='postgresql+psycopg://user:password@host/astra'
python scripts/load_infrastructure_postgis.py data/critical_infrastructure.geojson
```

The collector issues one Overpass query per hospital, school, airport, highway, railway, emergency facility, state boundary (administrative level 4), and district boundary (administrative level 6 or 8) over the complete `(6,68,38,98)` domain. It writes exposure features to `critical_infrastructure.geojson` and relation geometry to `administrative_boundaries.geojson`. OSM coverage is not authoritative: feature tagging and density vary by state, linear highways/railways may exceed public Overpass resource limits, and real-world facilities can be missing. It fails rather than writes a partial national layer. Run the three-state mapping-density spot-check before use, retain the generated report with the layer, and validate against official state/IMD sources before operational use. PostGIS loading requires a user-supplied database; no database is configured in this workspace.

### OpenStreetMap attribution and ODbL

The generated infrastructure and boundary layers contain OpenStreetMap data and are marked `© OpenStreetMap contributors`, licensed under the [Open Data Commons Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/). Preserve that attribution and licence notice with any redistributed dataset, derivative database, or map/export that uses these layers. Any frontend credit for this data must visibly say **© OpenStreetMap contributors** and link to [openstreetmap.org/copyright](https://www.openstreetmap.org/copyright).

Population density is supported as an explicit numeric path/cell input to the Impact Index, but no licensed pan-India population layer was supplied; it defaults to zero rather than being guessed. Similarly, the caller must provide authoritative administrative boundaries for affected-area lookup.

## Backend API

The backend contract is in [API_CONTRACT.md](API_CONTRACT.md); its live schema is `/openapi.json`. The new API code is isolated in `astra_api/` and does not modify any frontend asset. It has no sample, mock, debug, or test-mode route in its production response surface.

```powershell
$env:ASTRA_NOWCAST_ARTIFACT='C:\secure\latest-phase3-phase4.json'
$env:ASTRA_AUDIT_DB='C:\secure\astra_audit.sqlite3'
python scripts/serve_api.py
```

## Deployment

The repository includes a two-container deployment. Nginx serves the static
frontend and proxies `/api/` to FastAPI over the private container network, so
browser requests remain same-origin and do not need CORS.

```powershell
Copy-Item .env.example .env
# Place a validated artifact in .\artifacts\latest-phase3-phase4.json, then
# set ASTRA_NOWCAST_ARTIFACT=/app/artifacts/latest-phase3-phase4.json in .env.
docker compose up --build -d
```

The application is then available at `http://localhost:8080`; `GET /healthz`
is the container health endpoint. The API is deliberately not published as a
host port. If it must be exposed separately, set `ASTRA_CORS_ORIGINS` to a
comma-separated allow-list of exact frontend origins—never `*` in a deployment
that handles authenticated traffic.

`ASTRA_NOWCAST_ARTIFACT` is optional for process startup, but it must point to
a mounted, validated Phase 3+4 JSON artifact before the live-nowcast endpoint
can return a cycle. The named `astra_audit` volume persists the SQLite audit
database for a single API replica; use a managed transactional database before
running multiple API replicas.

### Vercel Services

`vercel.json` deploys the Vite app at `/` and FastAPI at `/api/*`. The frontend
uses the existing relative `/api/...` URLs, so no CORS configuration or
browser-to-service binding is needed. `archive/ASTRA_figma_design` is excluded
from this deployment.

On Vercel, the API automatically runs read-only because local SQLite and a
mounted artifact file are not durable serverless storage. Consequently,
`/api/v1/warnings/drafts`, `/api/v1/audit/warning-decisions`, and warning
decision `POST`s return `503 READ_ONLY_DEPLOYMENT`; no local database is
created. `/api/v1/nowcast/latest` returns `503 NO_CURRENT_CYCLE` until a
durable artifact source is introduced. Configure third-party corroboration
keys only through Vercel Project Environment Variables, never in this repo.

`GET /api/v1/nowcast/latest` returns a validated canonical pan-India artifact, including all four six-lead probability/confidence cubes, tracked/risk-ranked storms and five-source data status. If no real artifact exists it returns `503`, rather than creating a demo result. Warning decisions are available only through `POST /api/v1/warnings/{warning_id}/decision`; they are audit-recorded and never transmit a warning. The API audit found no pre-existing backend in this checkout. The Mumbai-specific fixture is in the separately managed frontend `app.js`, which this work leaves untouched.
