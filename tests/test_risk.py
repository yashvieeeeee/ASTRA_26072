import geopandas as gpd
from shapely.geometry import Point, Polygon
from astra_pipeline.risk import warning_draft, severity_tier

def test_draft_is_deterministic_review_only_and_lists_exposure():
    facilities=gpd.GeoDataFrame({"name":["District Hospital","School"],"facility_type":["hospital","school"],"osm_id":[1,2]},geometry=[Point(77.1,20),Point(80,20)],crs=4326)
    admin=gpd.GeoDataFrame({"name":["Test District"]},geometry=[Polygon([(76.8,19.7),(77.5,19.7),(77.5,20.3),(76.8,20.3)])],crs=4326)
    track={"track_id":7,"position":{"latitude":20,"longitude":77},"velocity":{"speed_km_h":40,"direction_degrees":90},"trend":"growing"}
    draft=warning_draft(track,.85,.9,{"radar":.5,"satellite":.5},facilities,admin,[("city",77.2,20)])
    assert draft["status"].startswith("DRAFT_FOR_FORECASTER_REVIEW")
    assert draft["tier"] == "severe" and draft["exposed_infrastructure"][0]["name"] == "District Hospital"
    assert draft["eta"][0]["eta_minutes"] is not None

def test_severity_degrades_when_confidence_is_low():
    assert severity_tier(.9,.2,"growing") == "low"
