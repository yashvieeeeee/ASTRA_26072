import numpy as np
import xarray as xr
from astra_pipeline import PreprocessingPipeline, NowcastBaseline
from astra_pipeline.domain import LATITUDES, LONGITUDES

def ten_minute_fused_tensor():
    """Phase-1 shaped, full-domain held-out tensor with a translating rain cell."""
    times=np.datetime64("2026-06-01T00:00") + np.arange(12)*np.timedelta64(10,"m")
    yy,xx=np.indices((len(LATITUDES),len(LONGITUDES)))
    fields=[]
    for t in range(len(times)):
        fields.append(np.exp(-((yy-60)**2+(xx-(30+t))**2)/25))
    rain=np.asarray(fields)
    values=np.stack((rain,rain*.8),axis=1)
    return xr.Dataset({"atmospheric_state":(("time","feature","latitude","longitude"),values)},coords={"time":times,"feature":["precipitation_rate","lightning_proxy"],"latitude":LATITUDES,"longitude":LONGITUDES})

def test_baseline_scores_all_six_leads_on_10_minute_pan_india_test_tensor():
    scores=NowcastBaseline().evaluate(ten_minute_fused_tensor())
    assert scores.evaluated_origins.sel({"method":"persistence"}).values.tolist() == [10,9,8,7,6,5]
    assert np.isfinite(scores.score.sel({"method":"optical_flow", "metric":"csi"})).all()
    assert set(scores.lead_minutes.values.tolist()) == {10,20,30,40,50,60}

def test_30_minute_phase_one_sample_does_not_fabricate_10_minute_verification():
    scores=NowcastBaseline().evaluate(PreprocessingPipeline().run())
    assert np.isnan(scores.score.sel({"method":"persistence", "lead_minutes":10, "metric":"csi"}))
    assert scores.evaluated_origins.sel({"method":"persistence", "lead_minutes":30}).item() > 0
