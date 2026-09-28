# ASTRA pan-India data pipeline

This package implements the PRD data milestone for the whole locked ASTRA domain: **6–38°N, 68–98°E**, on an inclusive **0.25°** grid (129 × 121 cells). It is separate from the existing dashboard assets.

## Run the zero-credential demo

```powershell
python -m pip install -r requirements.txt
python scripts/run_sample.py
python -m pytest
```

The `sample` adapters generate a small deterministic five-timestep data cube. It exercises GPM-like rain, the three INSAT channels, a CAPE × rainfall lightning proxy, a pending station feed, and ERA5/GFS-like model fields. It deliberately covers the entire domain and emits JSON schemas in `schemas/`.

## Contracts and pipeline

`astra_pipeline/contracts.py` contains Pydantic metadata contracts and `DatasetContract` validation for every xarray payload. `SourceMetadata.model_json_schema()` and `FusedOutputMetadata.model_json_schema()` produce the source/fused JSON Schemas; the demo also writes one fixed JSON Schema per source in `schemas/`. Before fusion, every adapter is schema-validated. Processing is quality check → 0.25° regrid → 30-minute nearest-bucket alignment → point binning → derived 1000–500 mb bulk shear → lazy normalisation → four-frame last-hour sequences.

Gridded production sources open Zarr with `chunks="auto"`; reductions remain xarray/Dask lazy. Point batches are explicitly binned per observation interval, avoiding a seasonal grid materialisation.

## Credentials and production modes

| Adapter | Historical | Real-time | Setup |
|---|---|---|---|
| GPM IMERG | `GPM_3IMERGHH` Final | `GPM_3IMERGHHE` Early (~4 h) | NASA Earthdata `~/.netrc`; set `ASTRA_GPM_ZARR_URL` |
| Satellite (fixed `insat_3d_3dr` contract) | EUMETSAT Meteosat-9 IODC archive (45.5°E; Meteosat-8 historical) | EUMETSAT IODC latest feed | `config.json` (or `ASTRA_SATELLITE_CONFIG`): `satellite_provider: eumetsat_iodc`, plus staged `historical_url`/`latest_url` or `zarr_url` |
| Satellite alternate: INSAT-3D/3DR | MOSDAC archive | MOSDAC `latest=True` endpoint | Set the same `satellite_provider` flag to `mosdac`; existing `ASTRA_MOSDAC_CONFIG` and top-level MOSDAC endpoint keys remain supported |
| Lightning | synthetic CAPE × rain proxy | synthetic CAPE × rain proxy | none; contract has `is_synthetic: true` |
| Ground stations | mock schema | mock schema | **Pending real source selection**; contract has `pending_source: true` |
| NWP | ERA5 / cdsapi target | GFS Herbie/Open-Meteo target | set `ASTRA_ERA5_ZARR_URL` or `ASTRA_GFS_ZARR_URL`; use a CDS-generated Zarr/NetCDF staging target for ERA5 |

Use `PreprocessingPipeline().run("historical")` or `.run("realtime")` once endpoints are staged. EUMETSAT IODC is the default while MOSDAC approval is pending. To switch later, change one line in `config.json` from `"satellite_provider": "eumetsat_iodc"` to `"satellite_provider": "mosdac"`; no pipeline or model change is needed. The EUMETSAT adapter normalises SEVIRI `IR_108`, `IR_120`, and `WV_073` to the existing `ir1_brightness_temperature`, `tir1_brightness_temperature`, and `wv_brightness_temperature` Kelvin contract. Production endpoints must map their variable names/units to that fixed adapter contract; this is intentional so replacing a provider cannot change downstream behavior. The current NWP endpoint opener supports staged Zarr/NetCDF; a deployment may plug a `cdsapi`/Herbie fetcher into `NWPAdapter.production` without changing preprocessing.

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

The ground-station and lightning fields must never be presented as observations: their pending/synthetic status is carried into fused output metadata. The test suite includes an explicit full-domain assertion and a failing narrow-adapter case so a regional feed cannot quietly reduce coverage.

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
python scripts/fetch_infrastructure.py --output data/critical_infrastructure.geojson
$env:DATABASE_URL='postgresql+psycopg://user:password@host/astra'
python scripts/load_infrastructure_postgis.py data/critical_infrastructure.geojson
```

The collector issues one Overpass query per hospital, school, airport, highway, railway, and emergency facility over the complete `(6,68,38,98)` domain. OSM coverage is not authoritative: feature tagging and density vary by state, linear highways/railways may exceed public Overpass resource limits, and real-world facilities can be missing. It fails rather than writes a partial national layer. Run the three-state mapping-density spot-check before use, retain the generated report with the layer, and validate against official state/IMD sources before operational use. PostGIS loading requires a user-supplied database; no database is configured in this workspace.

Population density is supported as an explicit numeric path/cell input to the Impact Index, but no licensed pan-India population layer was supplied; it defaults to zero rather than being guessed. Similarly, the caller must provide authoritative administrative boundaries for affected-area lookup.

## Backend API

The backend contract is in [API_CONTRACT.md](API_CONTRACT.md); its live schema is `/openapi.json`. The new API code is isolated in `astra_api/` and does not modify any frontend asset. It has no sample, mock, debug, or test-mode route in its production response surface.

```powershell
$env:ASTRA_NOWCAST_ARTIFACT='C:\secure\latest-phase3-phase4.json'
$env:ASTRA_AUDIT_DB='C:\secure\astra_audit.sqlite3'
python scripts/serve_api.py
```

`GET /api/v1/nowcast/latest` returns a validated canonical pan-India artifact, including all four six-lead probability/confidence cubes, tracked/risk-ranked storms and five-source data status. If no real artifact exists it returns `503`, rather than creating a demo result. Warning decisions are available only through `POST /api/v1/warnings/{warning_id}/decision`; they are audit-recorded and never transmit a warning. The API audit found no pre-existing backend in this checkout. The Mumbai-specific fixture is in the separately managed frontend `app.js`, which this work leaves untouched.
