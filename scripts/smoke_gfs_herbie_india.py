"""Explicit live smoke test for the full GFS/Herbie pan-India NWP pull."""
from __future__ import annotations

import argparse
from time import perf_counter

from astra_pipeline.adapters import NWPAdapter, nwp_realtime_provider
from astra_pipeline.domain import LATITUDES, LONGITUDES


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the complete pan-India GFS/Herbie NWP smoke test.")
    parser.add_argument("--live", action="store_true", help="download live NOAA GFS subsets (required)")
    args = parser.parse_args()
    if not args.live:
        parser.error("refusing a live GFS pull without --live")
    if nwp_realtime_provider() != "gfs_herbie":
        parser.error("set ASTRA_NWP_REALTIME_PROVIDER=gfs_herbie before this smoke test")

    started = perf_counter()
    dataset = NWPAdapter().load("realtime")
    elapsed = perf_counter() - started
    print(f"GFS/Herbie pan-India pull complete: {len(LATITUDES) * len(LONGITUDES)} points, "
          f"{dataset.sizes['time']} forecast frames, run {dataset.attrs['run_time_utc']}, "
          f"{elapsed:.2f}s total time")


if __name__ == "__main__":
    main()
