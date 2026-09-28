"""OpenStreetMap Overpass collection for ASTRA's non-authoritative exposure layer."""
from __future__ import annotations
import json, time
from pathlib import Path
import requests

PAN_INDIA="(6,68,38,98)"
OVERPASS="https://overpass-api.de/api/interpreter"
# Each entry is one full-domain query. `nwr` includes mapped points and mapped linear/area features.
FACILITY_QUERIES={
 "hospital": 'nwr["amenity"="hospital"]', "school": 'nwr["amenity"="school"]',
 "airport": 'nwr["aeroway"="aerodrome"]', "highway": 'way["highway"]',
 "railway": 'way["railway"]', "emergency": 'nwr["emergency"]',
}
STATE_SPOT_CHECKS={"Kerala":(8,76,13,78),"Assam":(24,89,28,96),"Rajasthan":(23,69,30,78)}

def overpass_query(selector: str, bbox=PAN_INDIA, timeout=900, retries=4):
    query=f'[out:json][timeout:{timeout}];{selector}{bbox};out center tags;'
    headers={"User-Agent":"ASTRA-SIH-research/0.1 (non-authoritative OSM exposure layer)"}
    for attempt in range(retries):
        response=requests.get(OVERPASS,params={"data":query},headers=headers,timeout=timeout+60)
        if response.ok: return response.json()
        if attempt==retries-1: response.raise_for_status()
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
