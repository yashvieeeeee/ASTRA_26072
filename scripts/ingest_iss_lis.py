"""Batch ingest historical NASA ISS-LIS V3.0 NetCDF lightning granules."""
from __future__ import annotations
import argparse
from pathlib import Path
from astra_pipeline.iss_lis import INDIA_BBOX, ingest_iss_lis

parser = argparse.ArgumentParser(description="Stream historical ISS-LIS observations; never a live feed.")
parser.add_argument("--input-dir", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, default=Path("data/processed/iss_lis"))
parser.add_argument("--resolution", type=float, default=.25)
parser.add_argument("--interval", default="5min")
parser.add_argument("--limit", type=int)
parser.add_argument("--resume", action="store_true")
parser.add_argument("--force", action="store_true")
parser.add_argument("--bbox", nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH"), default=INDIA_BBOX)
args = parser.parse_args()
print(ingest_iss_lis(args.input_dir, args.output_dir, resolution=args.resolution, interval=args.interval, limit=args.limit, resume=args.resume, force=args.force, bbox=tuple(args.bbox)))
