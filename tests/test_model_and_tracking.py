import numpy as np
import torch
from astra_pipeline.model import AstraNowcastNet, multitask_focal_loss, mc_dropout_predict
from astra_pipeline.tracking import detect_storm_objects, HungarianStormTracker, tracking_quality

def test_multitask_convlstm_outputs_six_panels_and_mc_confidence():
    model=AstraNowcastNet(input_features=3,hidden_channels=8)
    x=torch.randn(1,4,3,16,16); output=model(x)
    assert output["storm_logits"].shape == (1,6,16,16)
    assert multitask_focal_loss(output,torch.zeros_like(output["storm_logits"]),torch.zeros_like(output["lightning_logits"])).item() >= 0
    uncertainty=mc_dropout_predict(model,x,passes=2)
    assert uncertainty["confidence"].shape == (1,2,6,16,16)

def test_hungarian_tracker_preserves_a_moving_object_identity():
    lat=np.arange(6.0,9.0,.25); lon=np.arange(68.0,71.0,.25)
    tracker=HungarianStormTracker(max_distance_km=100)
    for time,x in [("2024-05-01T00:10",4),("2024-05-01T00:20",5)]:
        image=np.zeros((len(lat),len(lon))); image[4:7,x:x+3]=.9
        tracker.update(detect_storm_objects(image,lat,lon,time,minimum_cells=4))
    assert len(tracker.tracks)==1 and tracker.tracks[0].report()["observations"]==2
    assert tracking_quality(tracker)["identity_continuity"] == 1.0
