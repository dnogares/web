import os
import pandas as pd
import json
from pathlib import Path
from typing import Dict, List, Optional
import logging
import geopandas as gpd
from shapely.geometry import shape

logger = logging.getLogger(__name__)

class IntersectionService:
    def __init__(self, data_dir: str = "/app/capas"):
        # Ruta donde Easypanel monta tu volumen
        self.data_dir = Path(data_dir)
        self.wms_config_path = self.data_dir / "wms" / "capas_wms.csv"
        logger.info(f"[IntersectionService] Iniciado con volumen en: {data_dir}")

    def listar_capas_configuradas(self) -> List[Dict]:
        """Lee el archivo capas_wms.csv que creaste por consola"""
        if not self.wms_config_path.exists():
            logger.error(f"Archivo de configuración no encontrado: {self.wms_config_path}")
            return []
        df = pd.read_csv(self.wms_config_path)
        return df.to_dict(orient='records')

    def obtener_leyenda_local(self, nombre_capa: str) -> List[Dict]:
        """Carga los colores y etiquetas desde tus archivos leyenda_xxx.csv"""
        archivo = self.data_dir / "wms" / f"leyenda_{nombre_capa.lower()}.csv"
        if archivo.exists():
            return pd.read_csv(archivo).to_dict(orient='records')
        return []

    def analizar_intersecciones(self, geometria_parcela_gdf: gpd.GeoDataFrame) -> List[Dict]:
        """Cruza la parcela con los GPKG locales del volumen"""
        resultados = []
        capas = self.listar_capas_configuradas()

        for capa in capas:
            gpkg_path = self.data_dir / "gpkg" / capa['gpkg']
            if gpkg_path.exists():
                try:
                    # Cargar capa del volumen
                    gdf_capa = gpd.read_file(gpkg_path)
                    
                    # Asegurar que el sistema de coordenadas coincida (EPSG:4326)
                    if gdf_capa.crs != geometria_parcela_gdf.crs:
                        gdf_capa = gdf_capa.to_crs(geometria_parcela_gdf.crs)
                    
                    # Intersección espacial
                    interseccion = gpd.sjoin(geometria_parcela_gdf, gdf_capa, how="inner", predicate="intersects")
                    
                    if not interseccion.empty:
                        leyenda = self.obtener_leyenda_local(capa['nombre'])
                        resultados.append({
                            "capa": capa['nombre'],
                            "afectado": True,
                            "info_adicional": interseccion.drop(columns='geometry').to_dict(orient='records'),
                            "leyenda": leyenda
                        })
                except Exception as e:
                    logger.error(f"Error analizando capa {capa['nombre']}: {e}")
        
        return resultados
