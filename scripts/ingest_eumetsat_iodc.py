"""Manual EUMETSAT IODC archive/live ingestion command; never use it in CI."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path
from astra_pipeline.eumetsat_iodc import EUMETSATIODCDownloader, IODCStager, SatpySEVIRIReader

def ingest(products, downloader, stager):
    """Stage every available raw scene, whether downloaded now or reused from disk."""
    for product in products:
        product_id = str(product)
        downloaded = downloader.download(product)
        scene = downloader.raw_path(product_id)
        if not scene.is_file() or not scene.stat().st_size:
            raise RuntimeError(f"IODC scene {product_id} is neither downloaded nor available for staging")
        staged = stager.stage(scene, product_id)
        download_seconds = downloaded.download_seconds if downloaded else 0.0
        print(f"scene={product_id} bytes={scene.stat().st_size} download_s={download_seconds:.2f} decode_subset_s={staged.decode_subset_seconds:.2f} peak_memory_mib={staged.peak_memory_bytes / 1024 / 1024:.1f}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="UTC ISO-8601 start")
    parser.add_argument("--end", required=True, help="UTC ISO-8601 end")
    parser.add_argument("--directory", default="data/eumetsat_iodc")
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()
    parse = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    downloader = EUMETSATIODCDownloader(Path(args.directory) / "raw")
    stager = IODCStager(Path(args.directory) / "staged", SatpySEVIRIReader())
    ingest(downloader.find(parse(args.start), parse(args.end)), downloader, stager)
    stager.update_config(args.config)
