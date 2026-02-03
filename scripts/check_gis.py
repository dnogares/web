import fiona
import geopandas as gpd
import sys

print(f"Python Version: {sys.version}")
print(f"GeoPandas Version: {gpd.__version__}")
print(f"Fiona Version: {fiona.__version__}")

drivers = fiona.supported_drivers
fgb_supported = "FlatGeobuf" in drivers
print(f"FlatGeobuf supported in Fiona: {fgb_supported}")

if fgb_supported:
    print(f"Driver details for FlatGeobuf: {drivers['FlatGeobuf']}")

try:
    import pyogrio
    print(f"Pyogrio Version: {pyogrio.__version__}")
    pyogrio_drivers = pyogrio.list_drivers()
    print(f"FlatGeobuf in Pyogrio: {'FlatGeobuf' in pyogrio_drivers}")
except ImportError:
    print("Pyogrio not installed")
