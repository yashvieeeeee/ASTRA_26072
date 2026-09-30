from pathlib import Path
import numpy as np
from netCDF4 import Dataset

from astra_pipeline.iss_lis import extract_events, ingest_iss_lis


def _granule(path: Path):
    with Dataset(path, "w") as ds:
        ds.createDimension("event_dim", 2); ds.createDimension("group_dim", 2)
        def put(name, dim, values, dtype="f8", **attrs):
            variable = ds.createVariable(name, dtype, dim)
            variable[:] = values
            for key, value in attrs.items(): setattr(variable, key, value)
        put("lightning_event_lat", ("event_dim",), [20, 50])
        put("lightning_event_lon", ("event_dim",), [75, 10])
        put("lightning_event_TAI93_time", ("event_dim",), [915148800, 915148900], units="seconds since 1993-01-01 00:00:00.000")
        put("lightning_event_address", ("event_dim",), [4, 5], "i4")
        put("lightning_event_parent_address", ("event_dim",), [8, 9], "i4")
        put("lightning_group_address", ("group_dim",), [8, 9], "i4")
        put("lightning_group_parent_address", ("group_dim",), [2, 3], "i4")
        put("lightning_event_cluster_index", ("event_dim",), [98, 90], "i1")
        put("lightning_event_noise_index", ("event_dim",), [1, 2], "i1")
        put("lightning_event_alert_flag", ("event_dim",), [0, 0], "u1")
        put("lightning_event_radiance", ("event_dim",), [2, 3])
        put("lightning_event_footprint", ("event_dim",), [4, 5])
        put("lightning_event_observe_time", ("event_dim",), [10, 10], "i2")
        put("orbit_summary_id_number", (), 42, "i4")


def test_iss_lis_extract_and_resume(tmp_path):
    source = tmp_path / "ISS_LIS_SC_V3.0_20220101_000000_FIN.nc"; _granule(source)
    events, stats = extract_events(source)
    assert len(events) == 2 and events.flash_id.notna().all() and stats["orbit_id"] == 42
    result = ingest_iss_lis(tmp_path, tmp_path / "processed", interval="5min")
    assert result.processed == 1 and result.india_observations == 1
    resumed = ingest_iss_lis(tmp_path, tmp_path / "processed", interval="5min", resume=True)
    assert resumed.skipped == 1
    assert (tmp_path / "processed" / "lightning_grid_0.25deg_5m.parquet").exists()
