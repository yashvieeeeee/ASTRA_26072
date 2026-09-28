"""Deterministic forecaster-review risk assessment. It never sends a warning."""
from __future__ import annotations
from dataclasses import dataclass
import math
import geopandas as gpd
from shapely.geometry import Point, LineString
import torch

FACILITY_WEIGHTS={"hospital":10,"emergency":10,"airport":9,"railway":7,"highway":5,"school":4}
@dataclass(frozen=True)
class SeverityThresholds:
    moderate_probability: float=.30; high_probability: float=.55; severe_probability: float=.75
    minimum_confidence: float=.45

def severity_tier(probability, confidence, trend="steady", thresholds=SeverityThresholds()):
    adjusted=probability*confidence*(1.1 if trend=="growing" else .9 if trend=="decaying" else 1)
    if adjusted>=thresholds.severe_probability: return "severe"
    if adjusted>=thresholds.high_probability: return "high"
    if adjusted>=thresholds.moderate_probability and confidence>=thresholds.minimum_confidence: return "moderate"
    return "low"

def projected_path(track_report, minutes=60, radius_km=25):
    pos=track_report["position"]; velocity=track_report["velocity"]; speed=velocity["speed_km_h"]*minutes/60; bearing=math.radians(velocity["direction_degrees"])
    dlat=speed*math.cos(bearing)/111; dlon=speed*math.sin(bearing)/(111*max(math.cos(math.radians(pos["latitude"])),.1))
    line=LineString([(pos["longitude"],pos["latitude"]),(pos["longitude"]+dlon,pos["latitude"]+dlat)])
    return line.buffer(radius_km/111)

def eta_minutes(track_report, longitude, latitude):
    pos=track_report["position"]; velocity=track_report["velocity"]; speed=velocity["speed_km_h"]
    if speed<=0: return None
    dx=(longitude-pos["longitude"])*111*math.cos(math.radians(pos["latitude"])); dy=(latitude-pos["latitude"])*111
    bearing=math.radians(velocity["direction_degrees"]); forward=dx*math.sin(bearing)+dy*math.cos(bearing)
    return None if forward<0 else round(forward/speed*60,1)

def _intersections(frame, geometry):
    return frame[frame.geometry.apply(geometry.intersects)].copy()

def affected_areas(path, admin_boundaries: gpd.GeoDataFrame, name_column="name"):
    hit=_intersections(admin_boundaries,path)
    return hit[name_column].fillna("unnamed administrative area").tolist()

def exposed_infrastructure(path, infrastructure: gpd.GeoDataFrame):
    hit=_intersections(infrastructure,path)
    columns=[c for c in ("name","facility_type","osm_id") if c in hit]
    return hit[columns].fillna("unnamed").to_dict("records")

def impact_index(confidence, exposure, attribution, probability, population_density=0., population_density_reference=1000.):
    weighted=sum(FACILITY_WEIGHTS.get(item.get("facility_type"),1) for item in exposure)
    # Exposure raises priority without suppressing a warning in a low-exposure cell.
    facility_score=min(weighted/30,1)
    population_score=min(max(population_density,0)/population_density_reference,1)
    exposure_score=.7*facility_score+.3*population_score
    attribution={key:float(value) for key,value in attribution.items()}
    return round(100*(.45*confidence+.35*exposure_score+.20*probability),2), exposure_score, attribution

def gradient_source_attribution(model, inputs, feature_sources, head="storm", lead_index=0, latitude_index=0, longitude_index=0):
    """Gradient×input attribution for one predicted cell, aggregated to the five source families."""
    if len(feature_sources)!=inputs.shape[2]: raise ValueError("feature_sources must align with the fused feature axis")
    model.eval(); value=inputs.detach().clone().requires_grad_(True); model.zero_grad(set_to_none=True)
    logits=model(value)[f"{head}_logits"]; logits[0,lead_index,latitude_index,longitude_index].backward()
    contributions=(value.grad*value).abs().sum(dim=(0,1,3,4)).detach().cpu().numpy()
    grouped={}
    for source,amount in zip(feature_sources,contributions): grouped[source]=grouped.get(source,0.)+float(amount)
    total=sum(grouped.values()) or 1.; return {source:amount/total for source,amount in grouped.items()}

def warning_draft(track_report, probability, confidence, attribution, infrastructure: gpd.GeoDataFrame, admin_boundaries: gpd.GeoDataFrame, queried_locations=(), population_density=0.):
    path=projected_path(track_report); exposure=exposed_infrastructure(path,infrastructure); areas=affected_areas(path,admin_boundaries)
    index,exposure_score,attribution=impact_index(confidence,exposure,attribution,probability,population_density)
    etas=[{"name":name,"eta_minutes":eta_minutes(track_report,lon,lat)} for name,lon,lat in queried_locations]
    return {"status":"DRAFT_FOR_FORECASTER_REVIEW — NOT_DISPATCHED","track_id":track_report["track_id"],"tier":severity_tier(probability,confidence,track_report.get("trend","steady")),"probability":probability,"confidence":confidence,"affected_areas":areas,"eta":etas,"exposed_infrastructure":exposure,"impact_index":index,"exposure_score":exposure_score,"source_attribution":attribution}

def rank_warning_drafts(drafts):
    """Operational priority is Impact Index first, never raw storm probability alone."""
    return sorted(drafts,key=lambda draft:draft["impact_index"],reverse=True)
