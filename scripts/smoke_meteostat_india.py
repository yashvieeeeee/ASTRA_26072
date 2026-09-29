"""Manual network smoke test for Meteostat's Indian station coverage.

This is deliberately not part of pytest/CI.  It makes real Meteostat requests
and prints coverage evidence before a national 0.25 degree run is trusted.
"""
from datetime import datetime, timedelta, timezone

from meteostat import Hourly, Stations

CITIES = {"Mumbai": (19.076, 72.878), "Delhi": (28.614, 77.209),
          "Kolkata": (22.572, 88.364), "Chennai": (13.083, 80.270)}

# Meteostat 1.x expects timezone-naive UTC datetimes.
end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0, tzinfo=None)
start = end - timedelta(hours=24)
for city, (latitude, longitude) in CITIES.items():
    found = Stations().nearby(latitude, longitude).fetch(1)
    if found.empty:
        print(f"{city}: NO NEARBY METEOSTAT STATION — coverage unsuitable")
        continue
    station_id = found.index[0]
    distance = found.iloc[0].get("distance", "unknown")
    hourly = Hourly(station_id, start, end).fetch()
    fields = [field for field in ("temp", "rhum", "pres", "wspd", "prcp") if field in hourly and hourly[field].notna().any()]
    print(f"{city}: station={station_id}, distance_m={distance}, hourly_rows={len(hourly)}, populated_fields={','.join(fields) or 'NONE'}")
