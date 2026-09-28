import argparse,json
from astra_pipeline.infrastructure import download_pan_india_infrastructure,spot_check_report
p=argparse.ArgumentParser(); p.add_argument("--output",default="data/critical_infrastructure.geojson"); p.add_argument("--spot-check-only",action="store_true"); a=p.parse_args()
if a.spot_check_only: print(json.dumps(spot_check_report(),indent=2))
else: print(f"Wrote {len(download_pan_india_infrastructure(a.output)['features'])} OSM features to {a.output}")
