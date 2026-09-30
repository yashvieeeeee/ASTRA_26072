"""Print validated Open-Meteo atmospheric archive metadata and completeness."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from astra_pipeline.atmospheric import DEFAULT_DATASET_PATH, atmospheric_preview


parser = argparse.ArgumentParser(description="Preview ASTRA's historical Open-Meteo atmospheric archive.")
parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
args = parser.parse_args()
print(json.dumps(atmospheric_preview(args.dataset), indent=2))
