"""OpenStreetMap Overpass collection for ASTRA's non-authoritative exposure layer."""
from __future__ import annotations
import json, time
from pathlib import Path
import requests

PAN_INDIA="(6,68,38,98)"
OVERPASS_ENDPOINTS=("https://overpass-api.de/api/interpreter","https://overpass.kumi.systems/api/interpreter")
# Each entry is one full-domain query. `nwr` includes mapped points and mapped linear/area features.
FACILITY_QUERIES={
 "hospital": 'nwr["amenity"="hospital"]', "school": 'nwr["amenity"="school"]',
 "airport": 'nwr["aeroway"="aerodrome"]',
 # National exposure uses mapped arterial corridors. Querying every residential,
 # service and path way over India is not feasible on public Overpass instances.
 "highway": 'way["highway"~"^(motorway|trunk|primary|secondary)$"]',
 "railway": 'way["railway"~"^(rail|light_rail|subway)$"]', "emergency": 'nwr["emergency"]',
}
STATE_SPOT_CHECKS={"Kerala":(8,76,13,78),"Assam":(24,89,28,96),"Rajasthan":(23,69,30,78)}

def overpass_query(selector: str, bbox=PAN_INDIA, timeout=900, retries=4, output="center tags"):
    """Query Overpass with a bounded retry/failover policy.

    `output="geom tags"` is used for administrative relation geometry; point
    centres are intentionally retained for the exposure layer to keep it small.
    """
    query=f'[out:json][timeout:{timeout}];{selector}{bbox};out {output};'
    headers={"User-Agent":"ASTRA-SIH-research/0.1 (non-authoritative OSM exposure layer)"}
    for attempt in range(retries):
        endpoint=OVERPASS_ENDPOINTS[attempt % len(OVERPASS_ENDPOINTS)]
        try:
            response=requests.get(endpoint,params={"data":query},headers=headers,timeout=timeout+60)
            if response.ok: return response.json()
            if attempt==retries-1: response.raise_for_status()
        except requests.RequestException:
            if attempt==retries-1: raise
        time.sleep(2**attempt)

def _feature(element, facility_type):
    lat=element.get("lat",element.get("center",{}).get("lat")); lon=element.get("lon",element.get("center",{}).get("lon"))
    if lat is None or lon is None: return None
    tags=element.get("tags",{})
    return {"type":"Feature","geometry":{"type":"Point","coordinates":[lon,lat]},"properties":{"osm_type":element["type"],"osm_id":element["id"],"facility_type":facility_type,"name":tags.get("name"),"tags":tags,"source":"OpenStreetMap/Overpass","coverage_status":"non_authoritative"}}

def download_pan_india_infrastructure(output: str | Path):
    """Run exactly one complete 6–38N/68–98E query per declared facility type."""
    features=[]; failures={}
    for kind,selector in FACILITY_QUERIES.items():
        try:
            payload=overpass_query(selector); features.extend(f for e in payload.get("elements",[]) if (f:=_feature(e,kind)))
        except Exception as exc: failures[kind]=str(exc)
    if failures: raise RuntimeError(f"Incomplete national collection; no authoritative layer written. Failed: {failures}")
    collection={"type":"FeatureCollection","features":features,"metadata":{"bbox":[68,6,98,38],"facility_types":list(FACILITY_QUERIES),"source":"OpenStreetMap Overpass","license":"ODbL","coverage_status":"NON_AUTHORITATIVE — mapping completeness varies by state and feature type."}}
    Path(output).parent.mkdir(parents=True,exist_ok=True); Path(output).write_text(json.dumps(collection))
    return collection

ADMIN_BOUNDARY_QUERIES={"state": 'rel["boundary"="administrative"]["admin_level"="4"]', "district": 'rel["boundary"="administrative"]["admin_level"~"^(6|8)$"]'}

def _boundary_feature(element, boundary_type):
    """Turn relation member geometries returned by `out geom` into GeoJSON.

    Overpass supplies ordered way-member coordinates. They are kept as separate
    polygon rings when a relation has multiple outers, which is valid MultiPolygon
    geometry and avoids fabricating joins across incomplete OSM relations.
    """
    rings=[]
    for member in element.get("members",[]):
        coordinates=member.get("geometry")
        if member.get("role") not in ("outer", "") or not coordinates: continue
        ring=[[point["lon"],point["lat"]] for point in coordinates]
        if len(ring)>=4:
            if ring[0] != ring[-1]: ring.append(ring[0])
            rings.append([ring])
    if not rings: return None
    tags=element.get("tags",{})
    return {"type":"Feature","geometry":{"type":"MultiPolygon","coordinates":rings},"properties":{"osm_type":"relation","osm_id":element["id"],"boundary_type":boundary_type,"admin_level":tags.get("admin_level"),"name":tags.get("name"),"name_en":tags.get("name:en"),"tags":tags,"source":"OpenStreetMap/Overpass","license":"ODbL-1.0","coverage_status":"non_authoritative"}}

def download_pan_india_boundaries(output: str | Path):
    """Collect OSM state (level 4) and district (level 6/8) relations as GeoJSON."""
    features=[]; failures={}
    for boundary_type,selector in ADMIN_BOUNDARY_QUERIES.items():
        try:
            payload=overpass_query(selector, timeout=900, output="geom tags")
            features.extend(feature for element in payload.get("elements",[]) if (feature:=_boundary_feature(element,boundary_type)))
        except Exception as exc: failures[boundary_type]=str(exc)
    if failures: raise RuntimeError(f"Incomplete administrative boundary collection; no layer written. Failed: {failures}")
    collection={"type":"FeatureCollection","features":features,"metadata":{"bbox":[68,6,98,38],"boundary_types":list(ADMIN_BOUNDARY_QUERIES),"source":"OpenStreetMap Overpass","license":"ODbL-1.0","attribution":"© OpenStreetMap contributors","coverage_status":"NON_AUTHORITATIVE — administrative tagging and geometry completeness vary."}}
    Path(output).parent.mkdir(parents=True,exist_ok=True); Path(output).write_text(json.dumps(collection,ensure_ascii=False))
    return collection

def spot_check_report():
    """Availability/mapping-density checks, not a claim of real-world completeness."""
    def count(selector,bbox):
        query=f'[out:json][timeout:120];{selector}({",".join(map(str,bbox))});out count;'
        response=requests.get(OVERPASS,params={"data":query},headers={"User-Agent":"ASTRA-SIH-research/0.1"},timeout=180)
        response.raise_for_status()
        return int(response.json()["elements"][0]["tags"].get("total",0))
    report={}
    for state,bbox in STATE_SPOT_CHECKS.items():
        report[state]={}
        for kind,selector in {"hospital":FACILITY_QUERIES["hospital"],"school":FACILITY_QUERIES["school"],"emergency":FACILITY_QUERIES["emergency"]}.items():
            report[state][kind]=count(selector,bbox)
    return report
