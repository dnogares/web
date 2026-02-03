
import sys
import os

# Mock configuration
cfg = {"rutas": {"outputs": "outputs"}}

# Try to import CatastroDownloader
try:
    from catastro4 import CatastroDownloader
except ImportError:
    print("Error: catastro4.py not found in current directory")
    sys.exit(1)

def test_repro(ref):
    print(f"Testing reproduction for ref: {ref}")
    downloader = CatastroDownloader(output_dir=cfg["rutas"]["outputs"])
    
    # Simulate the logic from main.py:get_referencia_geojson
    gml_descargado = downloader.descargar_parcela_gml(ref)
    coords_poligono = None
    
    if gml_descargado:
        # Note: catastro4.py might be creating a subfolder with the ref name
        gml_path = os.path.join(cfg["rutas"]["outputs"], ref, f"{ref}_parcela.gml")
        if not os.path.exists(gml_path):
            # Fallback to direct path in output_dir
            gml_path = os.path.join(cfg["rutas"]["outputs"], f"{ref}_parcela.gml")
            
        if os.path.exists(gml_path):
            coords_poligono = downloader.extraer_coordenadas_gml(gml_path)
            print(f"Extracted {len(coords_poligono) if coords_poligono else 0} rings.")
        else:
            print(f"GML path not found: {gml_path}")
            return

    if coords_poligono and len(coords_poligono) > 0:
        anillo_exterior = coords_poligono[0]
        # The coordinates come as (lat, lon) from extraer_coordenadas_gml according to my read of catastro4.py
        # polygon_geojson = [[lon, lat] for lat, lon in anillo_exterior]
        
        # In main.py:
        # polygon_geojson = [[lon, lat] for lat, lon in anillo_exterior]
        # sample_lon, sample_lat = polygon_geojson[0]
        # if not (-10 <= sample_lon <= 5 and 36 <= sample_lat <= 44):
        #     print(f"⚠️ Coordenadas fuera de España: {sample_lat}, {sample_lon}")
        
        print(f"First 3 points (lat, lon): {anillo_exterior[:3]}")
        
        # Test original main.py logic
        lat0, lon0 = anillo_exterior[0]
        # main.py does: [[lon, lat] for lat, lon in anillo_exterior]
        # wait, let's check catastro4.py EXTRACTION logic again carefully.
        
        print("Checking validation range...")
        print(f"Sample Lat: {lat0}, Lon: {lon0}")
        if not (-10 <= lon0 <= 5 and 36 <= lat0 <= 44):
             print(f"VERDICT: OUTSIDE SPAIN (Logic: -10 <= lon <= 5 and 36 <= lat <= 44)")
        else:
             print(f"VERDICT: INSIDE SPAIN")

if __name__ == "__main__":
    test_repro("8884601WF4788S0020LL")
