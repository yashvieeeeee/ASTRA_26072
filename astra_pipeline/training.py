"""Window construction, stratified sampling, training and model evaluation."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import xarray as xr
import torch
from torch.utils.data import Dataset, DataLoader, WeightedRandomSampler
from .domain import assert_pan_india
from .model import multitask_focal_loss, mc_dropout_predict
from .baselines import LEAD_MINUTES, categorical_scores
from .tracking import detect_storm_objects, HungarianStormTracker, tracking_quality

TRAINING_WINDOWS=((np.datetime64("2024-04-01"),np.datetime64("2024-07-01")),(np.datetime64("2024-07-01"),np.datetime64("2024-09-01")))

@dataclass(frozen=True)
class TrainingConfig:
    input_frames: int=4
    storm_threshold: float=.5
    lightning_threshold: float=.5
    batch_size: int=2
    epochs: int=5
    learning_rate: float=1e-3

def _feature(fused, name):
    if name not in fused.feature.values: raise ValueError(f"Required fused feature {name!r} is missing")
    return fused.atmospheric_state.sel(feature=name)

class FusedWindowDataset(Dataset):
    """Lazy per-window access; no full seasonal cube is materialised."""
    def __init__(self, fused: xr.Dataset, config=TrainingConfig(), training_only=True):
        assert_pan_india(fused)
        self.fused=fused; self.config=config
        self.times=fused.time.values
        self.storm=_feature(fused,"precipitation_rate"); self.lightning=_feature(fused,"lightning_proxy")
        self.indices=[]; cadence=np.diff(self.times).astype("timedelta64[m]").astype(int)
        if len(cadence) and np.any(cadence != 10):
            raise ValueError("Six 10-minute leads require a 10-minute Phase 1 fused tensor; do not upsample 30-minute observations.")
        for i in range(config.input_frames-1,len(self.times)):
            targets=[self.times[i]+np.timedelta64(int(lead),"m") for lead in LEAD_MINUTES]
            if not all(np.any(self.times==target) for target in targets): continue
            if training_only and not any(start <= self.times[i] < end for start,end in TRAINING_WINDOWS): continue
            self.indices.append(i)
        if not self.indices: raise ValueError("No usable training windows in Apr–Jun or Jul–Aug 2024 with all six future targets.")
        self.positive=np.array([bool((self.storm.isel(time=i).data > config.storm_threshold).any().compute() if hasattr(self.storm.data,"compute") else (self.storm.isel(time=i).data > config.storm_threshold).any()) for i in self.indices])
    def __len__(self): return len(self.indices)
    def __getitem__(self,index):
        i=self.indices[index]; start=i-self.config.input_frames+1
        x=np.asarray(self.fused.atmospheric_state.isel(time=slice(start,i+1)).transpose("time","feature","latitude","longitude"),dtype=np.float32)
        storm=[]; lightning=[]
        for lead in LEAD_MINUTES:
            j=int(np.flatnonzero(self.times==self.times[i]+np.timedelta64(int(lead),"m"))[0])
            storm.append(np.asarray(self.storm.isel(time=j)>self.config.storm_threshold,dtype=np.float32))
            lightning.append(np.asarray(self.lightning.isel(time=j)>self.config.lightning_threshold,dtype=np.float32))
        return torch.from_numpy(x),torch.from_numpy(np.stack(storm)),torch.from_numpy(np.stack(lightning)),str(self.times[i])

def stratified_loader(dataset: FusedWindowDataset, config=TrainingConfig()):
    n_pos=max(int(dataset.positive.sum()),1); n_neg=max(len(dataset)-n_pos,1)
    weights=np.where(dataset.positive, .5/n_pos, .5/n_neg)
    return DataLoader(dataset,batch_size=config.batch_size,sampler=WeightedRandomSampler(weights,len(weights),replacement=True))

def train_model(model, dataset: FusedWindowDataset, config=TrainingConfig(), device="cpu"):
    model.to(device); optimizer=torch.optim.AdamW(model.parameters(),lr=config.learning_rate)
    history=[]
    for _ in range(config.epochs):
        model.train(); losses=[]
        for x,storm,lightning,_ in stratified_loader(dataset,config):
            pred=model(x.to(device)); loss=multitask_focal_loss(pred,storm.to(device),lightning.to(device))
            optimizer.zero_grad(); loss.backward(); optimizer.step(); losses.append(loss.item())
        history.append(float(np.mean(losses)))
    return history

def reliability_diagram(probabilities, labels, bins=10):
    probabilities=np.asarray(probabilities).ravel(); labels=np.asarray(labels).ravel(); edges=np.linspace(0,1,bins+1); rows=[]
    for lo,hi in zip(edges[:-1],edges[1:]):
        pick=(probabilities>=lo)&((probabilities<hi) if hi<1 else (probabilities<=hi))
        rows.append((float((lo+hi)/2),int(pick.sum()),float(probabilities[pick].mean()) if pick.any() else np.nan,float(labels[pick].mean()) if pick.any() else np.nan))
    return xr.Dataset({"count":("bin",[r[1] for r in rows]),"mean_predicted_probability":("bin",[r[2] for r in rows]),"observed_frequency":("bin",[r[3] for r in rows])},coords={"bin":[r[0] for r in rows]})

@torch.no_grad()
def evaluate_model(model, dataset: FusedWindowDataset, device="cpu", mc_passes=12):
    """POD/FAR/CSI, per-cell confidence reliability, and explicit full-domain audit."""
    model.to(device); all_probs=[]; all_conf=[]; all_storm=[]; all_lightning=[]
    for x,storm,lightning,_ in DataLoader(dataset,batch_size=1,shuffle=False):
        out=mc_dropout_predict(model,x.to(device),mc_passes)
        all_probs.append(out["probability"].cpu().numpy()); all_conf.append(out["confidence"].cpu().numpy())
        all_storm.append(storm.numpy()); all_lightning.append(lightning.numpy())
    probs=np.concatenate(all_probs); conf=np.concatenate(all_conf); storm=np.concatenate(all_storm); lightning=np.concatenate(all_lightning)
    scores=np.full((2,6,3),np.nan)
    for head,(p,y) in enumerate(((probs[:,0],storm),(probs[:,1],lightning))):
        for lead in range(6):
            values=[categorical_scores(p[n,lead],y[n,lead],.5) for n in range(len(p))]
            for metric,key in enumerate(("pod","far","csi")):
                metric_values=np.asarray([v[key] for v in values],dtype=float)
                scores[head,lead,metric]=metric_values[np.isfinite(metric_values)].mean() if np.isfinite(metric_values).any() else np.nan
    # Reliability measures whether predicted confidence agrees with actual correct classification.
    correctness=((probs>=.5)==np.stack((storm,lightning),axis=1)).astype(float)
    reliability=reliability_diagram(conf,correctness)
    result=xr.Dataset({"score":(("head","lead_minutes","metric"),scores)},coords={"head":["storm","lightning"],"lead_minutes":LEAD_MINUTES,"metric":["pod","far","csi"]})
    result.attrs.update({"evaluation_domain":"6–38N, 68–98E inclusive at 0.25 degrees","spatial_shape":"129x121","confidence_method":f"MC dropout ({mc_passes} passes)"})
    # Object continuity on the six predicted lead panels. A labelled object catalogue can
    # supply expected transitions to tracking_quality for a strict ID preservation score.
    continuity=[]
    for sample in probs[:,0]:
        tracker=HungarianStormTracker()
        for lead,panel in zip(LEAD_MINUTES,sample):
            objects=detect_storm_objects(panel,dataset.fused.latitude.values,dataset.fused.longitude.values,
                np.datetime64("2000-01-01")+np.timedelta64(int(lead),"m"))
            tracker.update(objects)
        continuity.append(tracking_quality(tracker)["identity_continuity"])
    tracking=xr.Dataset({"identity_continuity":((),float(np.mean(continuity)) if continuity else np.nan)},attrs={"meaning":"Observed linked-track continuity over predicted lead panels; strict merge/split/ID accuracy requires independently labelled object tracks."})
    return result,reliability,tracking
