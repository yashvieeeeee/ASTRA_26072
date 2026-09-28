# Product Requirements Document (PRD)

## ASTRA — AI-based Storm Tracking & Risk Assessment

**SIH Problem Statement:** 26072
**Organization:** Ministry of Earth Sciences (MoES)
**Department:** India Meteorological Department (IMD)
**Category:** Software | **Theme:** Disaster Management

---

## 1. Problem Statement

Severe thunderstorms and lightning cause significant loss of life, livestock, and property across India every year, especially during pre-monsoon (Nor'wester) and monsoon seasons. Existing forecasting largely relies on Numerical Weather Prediction (NWP) models that operate at coarser temporal resolution (hours to days) and struggle to capture the rapid, localized evolution of convective storms. There is a need for a **short-range (0–6 hour) nowcasting system** that fuses multiple observation sources — radar, satellite, lightning, ground stations, and NWP model output — using AI/ML to predict thunderstorm and lightning risk with enough precision and lead time to act on, while keeping a trained forecaster in control of every warning that goes out.

## 2. Goal & Objectives

**Goal:** Build ASTRA, an end-to-end nowcasting system that turns raw atmospheric observations into forecaster-reviewed, location-specific storm and lightning warnings within a 0–6 hour horizon.

**Objectives:**
- O1: Ingest and reconcile five distinct observation sources into one spatiotemporally consistent picture of the atmosphere.
- O2: Predict not just "storm or no storm," but calibrated probability fields, individually tracked storm objects with motion/growth trends, and an honestly-reported confidence level per prediction.
- O3: Translate raw model output into operational risk information — severity tier, estimated arrival time, and which people and infrastructure sit in a storm's path.
- O4: Surface every prediction and risk assessment through a dashboard that supports human review, editing, and sign-off — never automatic dispatch of a warning.
- O5: Beat baseline persistence/extrapolation methods on standard verification metrics (POD, FAR, CSI), and report model confidence honestly rather than optimistically.

## 3. Target Users / Stakeholders

| User | Need |
|---|---|
| IMD forecasters | Faster, higher-resolution guidance, with full authority to approve, edit, or dismiss any system-generated warning |
| State Disaster Management Authorities (SDMA/NDMA) | Actionable, location- and infrastructure-specific alerts to trigger evacuation/precaution protocols |
| Aviation & power grid operators | Lightning risk for flight safety and grid protection |
| Farmers / general public | Localized advance warning via app/SMS, once a forecaster has approved it |

## 4. Scope

### In Scope
- Data ingestion for five source types: radar (or a public precipitation proxy), satellite imagery, lightning observations (real or a documented synthetic proxy), ground weather station readings, and NWP model fields.
- Preprocessing: quality checks, spatial regridding, temporal alignment, and fusion into a single multi-channel atmospheric state per time step.
- An ML/DL prediction stage producing, per future time step (10/20/30/40/50/60 min ahead): storm-field probability maps, lightning probability maps, individually tracked storm objects (position, motion, growth/decay), and a per-prediction confidence score.
- A risk-assessment layer that converts raw predictions into a severity tier, estimated time of arrival at named locations, affected administrative areas, and which known critical infrastructure (hospitals, schools, airports, highways, railways, emergency facilities) falls within a storm's projected path.
- **ASTRA Impact Index** (our differentiator — see Section 11): a single, explainable, prioritized risk score per storm cell, combining model confidence with what's actually at stake on the ground.
- A dashboard supporting map + time-slider review, per-storm drill-down, and an explicit approve / edit / dismiss workflow for every warning, with an audit trail of forecaster decisions.
- Model evaluation against standard meteorological verification metrics.

### Out of Scope (for prototype/hackathon phase)
- Operational integration with IMD's live production data feeds (requires MoU/access).
- Long-range (>6 hr) forecasting.
- Full national-scale real-time deployment infrastructure.
- Automatic dispatch of warnings without forecaster approval — this is a permanent design principle, not a phase-1 limitation.

## 5. Functional Requirements

| ID | Requirement |
|---|---|
| FR1 | System shall ingest radar/precipitation-proxy data at regular intervals (e.g., 10–30 min) |
| FR2 | System shall ingest satellite IR/water-vapor imagery |
| FR3 | System shall ingest lightning occurrence data (real strike data or a clearly labeled synthetic proxy) |
| FR4 | System shall ingest ground weather station readings — temperature, humidity, pressure, wind, rainfall |
| FR5 | System shall ingest/derive NWP-based convective indices (CAPE, CIN, wind shear, humidity profile) |
| FR6 | System shall align all five sources onto a common spatial grid and time step, flagging and handling missing/delayed sources gracefully |
| FR7 | System shall predict storm-field and lightning probability maps at 10-minute intervals out to 60 minutes |
| FR8 | System shall detect and track individual storm cells as discrete objects across time, reporting position, speed, direction, and whether each is intensifying or weakening |
| FR9 | System shall report a confidence score alongside every prediction, calibrated against historical accuracy rather than fixed or inflated |
| FR10 | System shall convert predictions into a risk tier (low/moderate/high/severe), estimated arrival time, and affected administrative area per storm |
| FR11 | System shall cross-reference storm paths against a critical-infrastructure dataset and list exposed facilities |
| FR12 | System shall compute the ASTRA Impact Index per storm cell and rank active cells by it |
| FR13 | System shall display predictions and risk output on an interactive map with a time slider and per-storm detail view |
| FR14 | System shall require explicit forecaster approval before any warning is treated as issued; forecasters must be able to edit or dismiss a system-generated warning |
| FR15 | System shall log every warning decision (approved/edited/dismissed, by whom, when) for accountability |
| FR16 | System shall report model performance metrics (POD, FAR, CSI) on a held-out test period |

## 6. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR1 | Inference latency low enough to be useful operationally (target: full nowcast cycle < 5 min) |
| NFR2 | Dashboard responsive on standard hardware, supports concurrent forecaster access |
| NFR3 | Modular architecture — any data source can be swapped (proxy dataset → real IMD feed) without redesigning the rest of the pipeline |
| NFR4 | Model outputs must be interpretable/explainable — including which input source most influenced a given prediction, not just a final number |
| NFR5 | System should degrade gracefully if one data source is delayed or missing, and say so visibly rather than silently |
| NFR6 | No warning may be transmitted to end recipients without an explicit forecaster approval action |

## 7. Success Metrics

- **Critical Success Index (CSI)** and **Probability of Detection (POD)** on test events, benchmarked against a persistence/optical-flow baseline.
- **False Alarm Ratio (FAR)** kept within acceptable operational bounds.
- Confidence calibration: predicted confidence should track observed accuracy (a well-calibrated system, not just a high-accuracy one).
- Storm-tracking quality: how consistently the system keeps identity of the same storm cell across consecutive time steps.
- Lead time achieved (useful skill retained through the full 60-minute horizon).
- Qualitative: forecaster feedback on dashboard usability, trust in the confidence/explainability output, and alert relevance (if demo'd to domain experts).

## 8. Constraints & Assumptions

- Real-time IMD radar/lightning feeds are not publicly accessible for hackathon prototyping; publicly available proxy datasets (ERA5/GFS, GPM IMERG, MOSDAC INSAT, public ground-station networks) will be used to demonstrate methodology, with a documented plan for swapping in IMD's operational feeds.
- Thunderstorm/lightning events are rare relative to total observations (class imbalance), which must be explicitly handled in model design and evaluation.
- Real lightning strike-location data is not available under a free/public licence for this prototype; a physically-motivated synthetic proxy is used instead and clearly labeled as such throughout.
- A critical-infrastructure dataset (hospitals, schools, airports, highways, railways, emergency facilities with locations) must be assembled or sourced from public GIS data for the risk-assessment layer to function.
- Team assumes access to GPU compute for training spatiotemporal deep learning models.

## 9. Milestones (Indicative)

| Phase | Deliverable |
|---|---|
| 1 | Data pipeline: ingestion + spatiotemporal alignment of all five sources |
| 2 | Baseline model (persistence / optical flow extrapolation) for benchmarking |
| 3 | ML/DL nowcasting model: probability fields + storm-object tracking + confidence scoring |
| 4 | Risk-assessment layer: severity tiers, ETA, infrastructure exposure, ASTRA Impact Index |
| 5 | Dashboard: map, time slider, per-storm detail, approve/edit/dismiss workflow with audit log |
| 6 | Evaluation report + demo |

## 10. Open Questions

- Exact spatial resolution across the locked Pan-India domain (6–38°N, 68–98°E)?
- Which public dataset best proxies IMD's radar/lightning network for demo purposes?
- What source will provide the critical-infrastructure GIS dataset (OpenStreetMap extract, a government open-data portal, or a manually curated subset across India)?
- Is SMS/push alerting required for the demo, or is dashboard-only sufficient for SIH judging?

## 11. Our Differentiator — The ASTRA Impact Index

Most nowcasting systems (including comparable approaches we reviewed) stop at telling a forecaster *where a storm is going and how confident the model is*. ASTRA goes one step further: for every tracked storm cell, we compute a single **Impact Index** that combines three things a forecaster would otherwise have to weigh manually under time pressure:

1. **Model confidence** for that specific cell's prediction (not a blanket system-wide accuracy figure — a per-cell, per-lead-time confidence).
2. **What's in the path** — a weighted exposure score built from the infrastructure and population data in that cell's projected track (a hospital or a rail corridor contributes more weight than open farmland, without excluding farmland from the warning entirely).
3. **Attribution** — alongside the Impact Index, we show *why* the model reached this prediction: a breakdown of how much each input source (radar, satellite, lightning, ground stations, NWP) contributed to this specific cell's forecast, so a forecaster isn't just told "62% probability" but can see whether that number is driven mainly by radar echo growth, a lightning-strike cluster, or model-derived instability.

The result is that active storms aren't just ranked by raw probability — they're ranked by **what actually matters to protect**, with the reasoning exposed rather than hidden. This is the piece of ASTRA that goes beyond reproducing a standard fusion-and-alert pipeline, and it's the feature we'd want to highlight most clearly in a demo.
