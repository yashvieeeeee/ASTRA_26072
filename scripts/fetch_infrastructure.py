import argparse,json
from astra_pipeline.infrastructure import download_pan_india_boundaries,download_pan_india_infrastructure,spot_check_report
p=argparse.ArgumentParser(); p.add_argument("--output",default="data/critical_infrastructure.geojson"); p.add_argument("--boundaries-output",default="data/administrative_boundaries.geojson"); p.add_argument("--spot-check-only",action="store_true"); a=p.parse_args()
if a.spot_check_only: print(json.dumps(spot_check_report(),indent=2))
else:
    infrastructure=download_pan_india_infrastructure(a.output)
    boundaries=download_pan_india_boundaries(a.boundaries_output)
    print(f"Wrote {len(infrastructure['features'])} OSM infrastructure features to {a.output}")
    print(f"Wrote {len(boundaries['features'])} OSM administrative boundaries to {a.boundaries_output}")
