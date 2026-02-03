from gis_db import GISDatabase
import json

def list_layers():
    db = GISDatabase()
    layers = db.get_available_layers(schema="afecciones")
    with open("layers_found.json", "w") as f:
        json.dump(layers, f, indent=2)
    print(f"Encontradas {len(layers)} capas.")

if __name__ == "__main__":
    list_layers()
