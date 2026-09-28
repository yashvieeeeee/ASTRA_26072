import argparse,os
import geopandas as gpd
from sqlalchemy import create_engine, text
p=argparse.ArgumentParser(); p.add_argument("geojson"); p.add_argument("--table",default="critical_infrastructure"); a=p.parse_args()
url=os.getenv("DATABASE_URL")
if not url: raise SystemExit("DATABASE_URL is required (e.g. postgresql+psycopg://user:pass@host/db); nothing was loaded.")
frame=gpd.read_file(a.geojson).to_crs(4326); engine=create_engine(url)
frame.to_postgis(a.table,engine,if_exists="replace",index=False)
with engine.begin() as c: c.execute(text(f'CREATE INDEX IF NOT EXISTS {a.table}_geom_gix ON {a.table} USING GIST (geometry)'))
print(f"Loaded {len(frame)} facilities into PostGIS table {a.table}")
