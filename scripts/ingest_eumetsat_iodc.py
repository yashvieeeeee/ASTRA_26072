"""Manual EUMETSAT IODC archive/live ingestion command; never use it in CI."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path
from astra_pipeline.eumetsat_iodc import EUMETSATIODCDownloader, IODCStager, SatpySEVIRIReader

parser = argparse.ArgumentParser()
parser.add_argument("--start", required=True, help="UTC ISO-8601 start")
parser.add_argument("--end", required=True, help="UTC ISO-8601 end")
parser.add_argument("--directory", default="data/eumetsat_iodc")
parser.add_argument("--config", default="config.json")
args = parser.parse_args()
parse = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
downloader = EUMETSATIODCDownloader(Path(args.directory) / "raw")
stager = IODCStager(Path(args.directory) / "staged", SatpySEVIRIReader())
for product in downloader.find(parse(args.start), parse(args.end)):
    downloaded = downloader.download(product)
    if downloaded is None:
        continue
    scene = downloader.raw_path(downloaded.product_id)
    staged = stager.stage(scene, downloaded.product_id)
    print(f"scene={downloaded.product_id} bytes={downloaded.bytes_downloaded} download_s={downloaded.download_seconds:.2f} decode_subset_s={staged.decode_subset_seconds:.2f} peak_memory_mib={staged.peak_memory_bytes / 1024 / 1024:.1f}")
stager.update_config(args.config)
