"""Run baselines on a serialized Phase-1 tensor or show sample availability."""
import argparse
import xarray as xr
from astra_pipeline import PreprocessingPipeline, NowcastBaseline

parser=argparse.ArgumentParser()
parser.add_argument("--fused-zarr", help="Phase 1 fused Zarr store; omitting it uses the bundled 30-min demo")
parser.add_argument("--test-start", help="ISO timestamp for the held-out test period")
args=parser.parse_args()
fused=xr.open_zarr(args.fused_zarr, chunks="auto") if args.fused_zarr else PreprocessingPipeline().run("sample")
scores=NowcastBaseline().evaluate(fused, args.test_start)
for method in scores.method.values:
    print(f"\n{method}")
    print("lead(min)  POD     FAR     CSI     origins")
    for lead in scores.lead_minutes.values:
        row=scores.score.sel({"method":method,"lead_minutes":lead})
        n=scores.evaluated_origins.sel({"method":method,"lead_minutes":lead}).item()
        print(f"{lead:>8}  {row.sel(metric='pod').item():.3f}   {row.sel(metric='far').item():.3f}   {row.sel(metric='csi').item():.3f}   {n:>7}")
print("NaN scores mean this tensor has no exact verifying observation at that lead; they are not zero scores.")
