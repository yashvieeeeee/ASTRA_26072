"""Manual MOSDAC INSAT-3DR L1C ASIA_MER smoke ingestion; never run in CI."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from astra_pipeline.contracts import Mode
from astra_pipeline.mosdac import DATASET_IDS, DEFAULT_BOUNDING_BOX, MOSDACDownloader, MOSDACStager


def ingest(scenes, downloader, stager):
    """Download at most the requested scenes once each, then report file/timing metrics."""
    for scene in scenes:
        downloaded = downloader.download(scene)
        raw = downloader.raw_path(scene)
        if downloaded is None and not raw.exists():
            print(f"scene={scene.identifier} status=missing")
            continue
        staged = stager.stage(raw, scene.identifier)
        download_seconds = downloaded.download_seconds if downloaded else 0.0
        print(f"scene={scene.identifier} bytes={raw.stat().st_size} download_s={download_seconds:.2f} decode_subset_s={staged.decode_subset_seconds:.2f} peak_memory_mib={staged.peak_memory_bytes / 1024 / 1024:.1f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manual MOSDAC smoke test (keep the date range tiny).")
    parser.add_argument("--start", required=True, help="UTC ISO-8601 start")
    parser.add_argument("--end", required=True, help="UTC ISO-8601 end")
    parser.add_argument("--directory", default="data/mosdac")
    parser.add_argument("--config", default="config.json", help="Shared non-secret satellite config to update")
    parser.add_argument("--mode", choices=["historical", "realtime"], default="historical")
    parser.add_argument("--dataset-id", action="append", choices=DATASET_IDS, default=None)
    parser.add_argument("--count", type=int, default=3, help="MOSDAC search/download cap for this smoke test")
    parser.add_argument("--bounding-box", default=DEFAULT_BOUNDING_BOX, help="MOSDAC boundingBox: minLon,minLat,maxLon,maxLat")
    args = parser.parse_args()
    parse = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    downloader = MOSDACDownloader(Path(args.directory) / "raw")
    stager = MOSDACStager(Path(args.directory) / "staged", mode=Mode(args.mode))
    scenes = downloader.find(parse(args.start), parse(args.end), args.dataset_id or DATASET_IDS,
                             count=args.count, bounding_box=args.bounding_box)
    if not scenes:
        print("No MOSDAC scenes found for requested range.")
    else:
        ingest(scenes, downloader, stager)
        stager.update_config(args.config)
