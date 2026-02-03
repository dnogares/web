import os
import requests
import zipfile
import shutil
from pathlib import Path
import geopandas as gpd

def descargar_vias_pecuarias():
    """
    Descarga la capa de Vías Pecuarias del MITECO y la convierte a GPKG local.
    """
    # Configuración
    url_descarga = "https://www.mapama.gob.es/app/descargas/descargafichero.aspx?f=vpecuarias.zip"
    dir_capas = Path("capas/gpkg")
    dir_capas.mkdir(parents=True, exist_ok=True)
    
    archivo_destino = dir_capas / "vias.gpkg"
    temp_dir = Path("temp_vias")
    zip_path = temp_dir / "vias.zip"
    
    print("="*60)
    print("🚜 DESCARGANDO VÍAS PECUARIAS DE ESPAÑA")
    print("="*60)
    
    try:
        # 1. Crear directorio temporal
        if temp_dir.exists(): shutil.rmtree(temp_dir)
        temp_dir.mkdir()
        
        # 2. Descargar ZIP
        print(f"⬇️  Descargando desde MITECO ({url_descarga})...")
        r = requests.get(url_descarga, stream=True)
        with open(zip_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        print("✅ Descarga completada.")
        
        # 3. Descomprimir
        print("📦 Descomprimiendo...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
            
        # 4. Buscar el archivo SHP (suele tener nombres largos)
        shp_file = next(temp_dir.rglob("*.shp"), None)
        if not shp_file:
            raise FileNotFoundError("No se encontró ningún archivo .shp en el ZIP descargado.")
        
        print(f"📄 Archivo encontrado: {shp_file.name}")
        
        # 5. Convertir a GPKG (EPSG:4326 para web)
        print("🔄 Convirtiendo a GeoPackage (esto puede tardar un poco)...")
        gdf = gpd.read_file(shp_file)
        
        # Asegurar proyección WGS84
        if gdf.crs and gdf.crs.to_string() != "EPSG:4326":
            print("   Re-proyectando a WGS84...")
            gdf = gdf.to_crs("EPSG:4326")
            
        # Guardar
        gdf.to_file(archivo_destino, driver="GPKG")
        print(f"✅ Archivo guardado en: {archivo_destino}")
        print("🎉 ¡Capa de Vías Pecuarias lista para usar en local!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        # Limpieza
        if temp_dir.exists():
            try:
                shutil.rmtree(temp_dir)
            except: pass

if __name__ == "__main__":
    descargar_vias_pecuarias()
