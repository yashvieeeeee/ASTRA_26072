# ASTRA data ingestion and preprocessing TDD

This design implements the PRD's first milestone.  The canonical spatial domain is inclusive `6.00..38.00°N`, `68.00..98.00°E` at `0.25°`; this is 129 × 121 cells.  It is deliberately a constant, rather than inferred from any incoming feed.

Each source implements `SourceAdapter.load(mode)`, returns an xarray dataset and validates it using its fixed `DatasetContract` before fusion.  Contracts also have Pydantic metadata models and exportable JSON Schemas.  Grid sources use `(time, latitude, longitude)`; lightning and stations use `(time, point)` and are binned into the grid.

`PreprocessingPipeline` performs quality validation, spatial interpolation/binning, nearest 30-minute time alignment, derived features, normalisation and four-frame (last hour) rolling sequences. Inputs stay xarray/Dask-backed: remote Zarr is opened with chunks and no `.load()`/`.values` call is used on a complete data cube. The small `sample` mode is deterministic synthetic data covering all India and requires no credentials.

Production-mode notes: GPM supports Earthdata authenticated Zarr/NetCDF endpoints (`GPM_3IMERGHH` historical, `GPM_3IMERGHHE` realtime); MOSDAC reads a configured Zarr/NetCDF endpoint and requires `config.json`; ERA5 is requested through `cdsapi` and GFS endpoint handling is delegated to a supplied Zarr/NetCDF URI (or a production Herbie/Open-Meteo adapter extension). Real ground-station selection remains an explicit pending open item, so its adapter is a clearly labelled mock with the production schema.

The fused result is a feature cube with a `feature` coordinate. `build_sequences` adds `sequence` and `input_step` dimensions; it asserts the complete canonical domain before returning. Missing sources are represented by NaN fields and provenance metadata rather than silently changing the domain.

## Baseline nowcasting

`NowcastBaseline` selects the fused `precipitation_rate` feature; it has no data adapters or external inputs. Persistence repeats the last field. Optical flow estimates dense local displacement from the preceding pair using Lucas–Kanade normal equations over a 9×9 window, then backward-warps the last field for the six requested leads. Evaluation uses exact target timestamps only and reports POD, FAR and CSI averaged over valid test origins. This is critical: the phase-1 sample is 30-minute cadence and cannot verify 10/20/40/50-minute scores; they are returned as NaN. Operational benchmark inputs need 10-minute fused test tensors, while the pipeline's 30-minute alignment remains the current Phase-1 prototype setting.

## Primary model

The Phase 3 default is `AstraNowcastNet`: four last-hour fused frames enter a shared convolutional ConvLSTM encoder. Its independently parameterized one-by-one convolution heads produce storm and lightning logits for T+10 through T+60. Focal BCE handles cell-level imbalance; `WeightedRandomSampler` balances windows containing an active storm against inactive windows. Only windows whose origin falls in Apr–Jun or Jul–Aug 2024 are trainable. MC dropout creates an inference ensemble; its agreement is a separate confidence field assessed by a reliability diagram, never merged into POD/FAR/CSI. Predicted storm maps go through eight-connected components and a distance-gated Hungarian tracker. Every window dataset and evaluation first asserts the canonical 129×121 pan-India grid.

## Risk assessment

The risk layer is deterministic and cannot dispatch warnings. It receives a Phase 3 storm track, probability, confidence and source attribution; projects a buffered motion path; intersects it with supplied administrative and infrastructure geometries; calculates location ETA; and returns a `DRAFT_FOR_FORECASTER_REVIEW` document. Severity uses configurable probability/confidence/trend thresholds. The Impact Index is 45% confidence, 35% capped critical-facility exposure and 20% probability; it deliberately adds priority without removing low-exposure warnings. Gradient×input attribution can aggregate fused feature contributions back to radar, satellite, lightning, ground, and NWP source families. OSM critical-infrastructure data is explicitly non-authoritative and requires spot-check/audit before operational use.
