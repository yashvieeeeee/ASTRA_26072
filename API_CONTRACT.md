# ASTRA backend API contract — v1

Base path: `/api/v1`. The API is backend-only and serves only the canonical pan-India domain: inclusive 6–38°N, 68–98°E at 0.25° (129 × 121). Any stored artifact outside that domain is rejected before it can be served.

## `GET /nowcast/latest`

Returns `200` with `NowcastResponse`, or `503 NO_CURRENT_CYCLE` when no real Phase 3+4 artifact has been published. There is no sample/mock fallback. `predictions` contains ordered 10–60 minute storm/lightning probability and confidence grids, while `storms` contains tracked-object/risk output. `data_status.sources` always lists `gpm_imerg`, `insat_3d_3dr`, `synthetic_lightning`, `ground_stations`, and `nwp`; the frontend must show degraded/stale status whenever `data_status.overall` is not `complete`.

## `GET /warnings/drafts`

Returns reviewable drafts only. A warning has `transmitted: false` in every API response.

## `POST /warnings/{warning_id}/decision`

Body: `{"actor_id":"forecaster-id","decision":"approve|edit|dismiss","edit":{...}}`. The endpoint is the only state-transition mechanism. It records an immutable audit event, timestamps it server-side, and returns the updated warning. Approval does **not** transmit a warning; no dispatch endpoint exists in this API.

## `GET /audit/warning-decisions`

Returns immutable decision records (`who`, `what`, `when`, edit payload). Optional `warning_id` and `limit` parameters support accountability review.

The live OpenAPI schema is `/openapi.json`; Pydantic types in `astra_api/schemas.py` define this contract. Production responses contain no `debug`, `mock`, `sample`, or test-mode flag.
