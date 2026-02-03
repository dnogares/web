import os
import geopandas as gpd
import logging
from pathlib import Path

# Configuración de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def convert_to_fgb(input_path, output_path=None):
    """Convierte un archivo geoespacial a FlatGeobuf."""
    try:
        input_path = Path(input_path)
        if not output_path:
            output_path = input_path.with_suffix('.fgb')
        else:
            output_path = Path(output_path)

        logger.info(f"Convirtiendo {input_path.name} -> {output_path.name}...")
        
        # Leer el archivo (GPKG, GeoJSON, SHP, KML...)
        gdf = gpd.read_file(str(input_path))
        
        if gdf.empty:
            logger.warning(f"Archivo vacío: {input_path}")
            return False

        # Asegurar que el CRS sea Web Mercator o WGS84 para compatibilidad
        if gdf.crs and gdf.crs.to_string() != "EPSG:4326":
            logger.info(f"Reproyectando {input_path.name} a EPSG:4326...")
            gdf = gdf.to_crs("EPSG:4326")

        # Guardar en formato FlatGeobuf
        # index=True crea el índice espacial (.fgi) necesario para range requests
        gdf.to_file(str(output_path), driver='FlatGeobuf', index=True)
        
        logger.info(f"✅ Conversión exitosa: {output_path}")
        return True
    except Exception as e:
        logger.error(f"❌ Error convirtiendo {input_path}: {e}")
        return False

def batch_convert(directory="capas"):
    """Busca archivos en el directorio y los convierte a FlatGeobuf."""
    extensions = ['.geojson', '.shp', '.gpkg', '.kml']
    base_path = Path(directory)
    
    if not base_path.exists():
        logger.error(f"El directorio {directory} no existe.")
        return

    count = 0
    for file_path in base_path.rglob('*'):
        if file_path.suffix.lower() in extensions:
            # Evitar reconvertir lo que ya es FlatGeobuf o archivos temporales
            if file_path.name.startswith('.'): continue
            
            fgb_path = file_path.with_suffix('.fgb')
            if fgb_path.exists():
                logger.info(f"Saltando {file_path.name}, ya existe la versión .fgb")
                continue
                
            if convert_to_fgb(file_path, fgb_path):
                count += 1
    
    logger.info(f"Proceso finalizado. {count} archivos convertidos.")

if __name__ == "__main__":
    batch_convert("capas")
    # También intentar con ccnn si existe
    if os.path.exists("ccnn"):
        batch_convert("ccnn")
