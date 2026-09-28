import numpy as np

LAT_MIN, LAT_MAX, LON_MIN, LON_MAX, RESOLUTION = 6.0, 38.0, 68.0, 98.0, 0.25
LATITUDES = np.round(np.arange(LAT_MIN, LAT_MAX + RESOLUTION / 2, RESOLUTION), 2)
LONGITUDES = np.round(np.arange(LON_MIN, LON_MAX + RESOLUTION / 2, RESOLUTION), 2)

def canonical_grid():
    return {"latitude": LATITUDES, "longitude": LONGITUDES}

def assert_pan_india(dataset):
    """Fail rather than accept an adapter whose coverage was silently narrowed."""
    for name, expected in canonical_grid().items():
        actual = dataset.coords.get(name)
        if actual is None or not np.array_equal(np.asarray(actual), expected):
            got = "missing" if actual is None else f"{float(actual.min()):.2f}..{float(actual.max()):.2f} ({actual.size})"
            raise ValueError(f"Pan-India coverage violation for {name}: expected {expected[0]:.2f}..{expected[-1]:.2f} ({len(expected)}), got {got}")
