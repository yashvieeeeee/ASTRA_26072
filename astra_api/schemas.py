from __future__ import annotations
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from astra_pipeline.domain import LATITUDES, LONGITUDES

class Strict(BaseModel): model_config=ConfigDict(extra="forbid")
class Domain(Strict):
    latitude: list[float]; longitude: list[float]; resolution_degrees: float=.25
    @model_validator(mode="after")
    def canonical(self):
        if self.latitude!=LATITUDES.tolist() or self.longitude!=LONGITUDES.tolist() or self.resolution_degrees!=.25: raise ValueError("Only the full canonical 6–38N / 68–98E domain may be served")
        return self
class SourceState(str,Enum): complete="complete"; delayed="delayed"; missing="missing"; synthetic="synthetic"; pending="pending"
class SourceStatus(Strict): source: str; state: SourceState; observed_at: datetime|None=None; reason: str|None=None
class DataStatus(Strict): overall: str; sources: list[SourceStatus]
class ProbabilityCube(Strict):
    lead_minutes: list[int]=Field(min_length=6,max_length=6)
    values: list[list[list[float]]]

    @field_validator("lead_minutes")
    @classmethod
    def leads(cls,v):
        if v != [10,20,30,40,50,60]: raise ValueError("Required leads are 10..60 minutes")
        return v
    @field_validator("values")
    @classmethod
    def cube_shape(cls,v):
        if len(v)!=6 or any(len(panel)!=129 or any(len(row)!=121 for row in panel) for panel in v): raise ValueError("Probability cubes must be [6,129,121]")
        return v
class Predictions(Strict):
    storm_probability: ProbabilityCube; lightning_probability: ProbabilityCube; storm_confidence: ProbabilityCube; lightning_confidence: ProbabilityCube
class TrackVelocity(Strict): speed_km_h: float; direction_degrees: float
class TrackedStorm(Strict):
    track_id: int; latitude: float; longitude: float; velocity: TrackVelocity; trend: str; probability: float; confidence: float; tier: str; impact_index: float; source_attribution: dict[str,float]; affected_areas: list[str]=[]; exposed_infrastructure: list[dict]=[]
class NowcastResponse(Strict): cycle_id: str; generated_at: datetime; domain: Domain; data_status: DataStatus; predictions: Predictions; storms: list[TrackedStorm]
class Decision(str,Enum): approve="approve"; edit="edit"; dismiss="dismiss"
class WarningDecisionRequest(Strict): actor_id: str=Field(min_length=1,max_length=128); decision: Decision; edit: dict|None=None
class WarningDraft(Strict): warning_id: str; status: str; transmitted: bool=False; payload: dict; created_at: datetime; decided_at: datetime|None=None; decided_by: str|None=None
class AuditEvent(Strict): warning_id: str; actor_id: str; decision: Decision; occurred_at: datetime; edit: dict|None=None
