"""Storm object extraction and Hungarian association for predicted probability maps."""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
from scipy.ndimage import label
from scipy.optimize import linear_sum_assignment

@dataclass
class StormObject:
    time: object; latitude: float; longitude: float; area_cells: int; mean_probability: float

@dataclass
class StormTrack:
    id: int; objects: list[StormObject]=field(default_factory=list)
    def report(self):
        latest=self.objects[-1]; velocity={"speed_km_h":0.,"direction_degrees":0.}
        trend="new"
        if len(self.objects)>1:
            previous=self.objects[-2]; dt=max((np.datetime64(latest.time)-np.datetime64(previous.time))/np.timedelta64(1,"h"),1e-6)
            dy=(latest.latitude-previous.latitude)*111; dx=(latest.longitude-previous.longitude)*111*np.cos(np.deg2rad(latest.latitude))
            velocity={"speed_km_h":float(np.hypot(dx,dy)/dt),"direction_degrees":float((np.degrees(np.arctan2(dx,dy))+360)%360)}
            trend="growing" if latest.area_cells>previous.area_cells else "decaying" if latest.area_cells<previous.area_cells else "steady"
        return {"track_id":self.id,"position":{"latitude":latest.latitude,"longitude":latest.longitude},"velocity":velocity,"trend":trend,"observations":len(self.objects)}

def detect_storm_objects(probability_map, latitudes, longitudes, time, threshold=.5, minimum_cells=4):
    labels,count=label(np.asarray(probability_map)>=threshold,structure=np.ones((3,3)))
    objects=[]
    for component in range(1,count+1):
        ys,xs=np.where(labels==component)
        if len(ys)<minimum_cells: continue
        objects.append(StormObject(time,float(np.mean(latitudes[ys])),float(np.mean(longitudes[xs])),len(ys),float(np.mean(np.asarray(probability_map)[ys,xs]))))
    return objects

class HungarianStormTracker:
    def __init__(self,max_distance_km=100.): self.max_distance_km=max_distance_km; self.tracks=[]; self._next_id=1
    @staticmethod
    def _distance(a,b):
        return np.hypot((a.latitude-b.latitude)*111,(a.longitude-b.longitude)*111*np.cos(np.deg2rad(a.latitude)))
    def update(self,objects):
        active=[track for track in self.tracks if track.objects]; unmatched=set(range(len(objects)))
        if active and objects:
            cost=np.array([[self._distance(t.objects[-1],obj) for obj in objects] for t in active]); rows,cols=linear_sum_assignment(cost)
            for row,col in zip(rows,cols):
                if cost[row,col]<=self.max_distance_km: active[row].objects.append(objects[col]); unmatched.discard(col)
        for index in unmatched:
            self.tracks.append(StormTrack(self._next_id,[objects[index]])); self._next_id+=1
        return [track.report() for track in self.tracks if track.objects]

def tracking_quality(tracker: HungarianStormTracker, expected_object_transitions: int | None = None):
    """Continuity diagnostic: linked transitions vs. independent/new tracks (merges/splits are surfaced)."""
    lengths=np.array([len(track.objects) for track in tracker.tracks])
    transitions=max(int(lengths.sum())-len(lengths),0)
    possible=expected_object_transitions if expected_object_transitions is not None else max(int(lengths.sum())-1,1)
    return {"tracks":int(len(lengths)),"linked_transitions":transitions,"identity_continuity":float(transitions/max(possible,1)),
            "single_frame_tracks":int((lengths==1).sum()),"note":"Pass independently labelled expected_object_transitions for strict ID preservation and merge/split loss accounting."}
