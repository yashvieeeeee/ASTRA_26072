"""Retired: Open-Meteo must not be used for ASTRA's full pan-India grid."""
from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Explain the retired Open-Meteo full-grid smoke test.")
    parser.parse_args()
    raise SystemExit("Open-Meteo is point-query fallback only. Use scripts/smoke_gfs_herbie_india.py --live for pan-India NWP.")


if __name__ == "__main__":
    main()
