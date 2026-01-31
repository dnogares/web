"""
Cliente Python para API OGC Features de MAPAMA
Permite descargar colecciones de datos geográficos con paginación y transformación CRS
"""

import requests
import geopandas as gpd
import pandas as pd
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
import logging
import time
from urllib.parse import urljoin
import json

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class OGCCollection:
    """Representa una colección de la API OGC Features"""
    id: str
    title: str
    description: str
    extent: Dict[str, Any]
    crs: str
    links: List[Dict[str, str]]

@dataclass
class OGCFeatureType:
    """Tipo de feature con sus propiedades consultables"""
    name: str
    type: str
    title: Optional[str] = None
    description: Optional[str] = None

class MAPAMAClient:
    """Cliente para interactuar con la API OGC Features de MAPAMA"""
    
    BASE_URL = "https://wmts.mapama.gob.es/sig-api/ogc/features/v1"
    DEFAULT_CRS = "EPSG:25830"  # ETRS89 UTM 30N para España peninsular
    DEFAULT_LIMIT = 5000
    TIMEOUT = 60
    
    def __init__(self, base_url: str = None, timeout: int = None):
        self.base_url = base_url or self.BASE_URL
        self.timeout = timeout or self.TIMEOUT
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'MAPAMA-OGC-Client/1.0',
            'Accept': 'application/json'
        })
    
    def _make_request(self, url: str, params: Dict = None) -> Dict:
        """Realiza petición HTTP con manejo de errores"""
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error en petición a {url}: {e}")
            raise
    
    def get_collections(self) -> List[OGCCollection]:
        """
        Obtiene todas las colecciones disponibles en la API
        
        Returns:
            Lista de colecciones OGC
        """
        logger.info("Obteniendo colecciones disponibles...")
        
        url = urljoin(self.base_url, "collections")
        data = self._make_request(url)
        
        collections = []
        for coll_data in data.get('collections', []):
            collection = OGCCollection(
                id=coll_data.get('id', ''),
                title=coll_data.get('title', ''),
                description=coll_data.get('description', ''),
                extent=coll_data.get('extent', {}),
                crs=coll_data.get('crs', []),
                links=coll_data.get('links', [])
            )
            collections.append(collection)
        
        logger.info(f"Encontradas {len(collections)} colecciones")
        return collections
    
    def get_collection_metadata(self, collection_id: str) -> Dict:
        """
        Obtiene metadatos detallados de una colección específica
        
        Args:
            collection_id: ID de la colección
            
        Returns:
            Metadatos de la colección
        """
        logger.info(f"Obteniendo metadatos de colección: {collection_id}")
        
        url = urljoin(self.base_url, f"collections/{collection_id}")
        return self._make_request(url)
    
    def get_queryables(self, collection_id: str) -> Dict[str, OGCFeatureType]:
        """
        Obtiene las propiedades consultables de una colección
        
        Args:
            collection_id: ID de la colección
            
        Returns:
            Diccionario de propiedades consultables
        """
        logger.info(f"Obteniendo propiedades consultables de: {collection_id}")
        
        url = urljoin(self.base_url, f"collections/{collection_id}/queryables")
        data = self._make_request(url)
        
        queryables = {}
        for prop_name, prop_data in data.get('properties', {}).items():
            feature_type = OGCFeatureType(
                name=prop_name,
                type=prop_data.get('$ref', prop_data.get('type', 'string')),
                title=prop_data.get('title'),
                description=prop_data.get('description')
            )
            queryables[prop_name] = feature_type
        
        return queryables
    
    def download_features(
        self,
        collection_id: str,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        limit: int = None,
        paginate: bool = True,
        properties: Optional[List[str]] = None,
        target_crs: str = None
    ) -> gpd.GeoDataFrame:
        """
        Descarga features de una colección con paginación automática
        
        Args:
            collection_id: ID de la colección
            bbox: Bounding box (minx, miny, maxx, maxy)
            limit: Límite de features a descargar
            paginate: Si usar paginación automática
            properties: Lista de propiedades específicas a descargar
            target_crs: CRS de destino (default: EPSG:25830)
            
        Returns:
            GeoDataFrame con los features descargados
        """
        logger.info(f"Descargando features de colección: {collection_id}")
        
        target_crs = target_crs or self.DEFAULT_CRS
        limit = limit or self.DEFAULT_LIMIT
        
        all_features = []
        offset = 0
        page_size = min(1000, limit)  # API suele limitar a 1000 por página
        
        while True:
            # Construir parámetros de la petición
            params = {
                'limit': page_size,
                'offset': offset
            }
            
            if bbox:
                params['bbox'] = ','.join(map(str, bbox))
            
            if properties:
                params['properties'] = ','.join(properties)
            
            # Realizar petición
            url = urljoin(self.base_url, f"collections/{collection_id}/items")
            
            try:
                data = self._make_request(url, params)
                
                features = data.get('features', [])
                if not features:
                    logger.info("No hay más features disponibles")
                    break
                
                all_features.extend(features)
                logger.info(f"Descargados {len(features)} features (total: {len(all_features)})")
                
                # Verificar límite
                if limit and len(all_features) >= limit:
                    all_features = all_features[:limit]
                    break
                
                # Verificar si hay más páginas
                if not paginate or len(features) < page_size:
                    break
                
                offset += page_size
                
                # Pequeña pausa para no sobrecargar la API
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error descargando página {offset}: {e}")
                break
        
        if not all_features:
            logger.warning("No se descargaron features")
            return gpd.GeoDataFrame()
        
        # Convertir a GeoDataFrame
        logger.info("Convirtiendo features a GeoDataFrame...")
        gdf = gpd.GeoDataFrame.from_features(all_features)
        
        # Transformar CRS si es necesario
        if gdf.crs and gdf.crs.to_string() != target_crs:
            logger.info(f"Transformando CRS de {gdf.crs} a {target_crs}")
            gdf = gdf.to_crs(target_crs)
        
        logger.info(f"Descargado GeoDataFrame con {len(gdf)} features")
        return gdf
    
    def download_by_namespace(
        self,
        namespace: str,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        limit: int = None
    ) -> Dict[str, gpd.GeoDataFrame]:
        """
        Descarga todas las colecciones de un namespace
        
        Args:
            namespace: Namespace (ej: 'biodiversidad', 'alimentacion')
            bbox: Bounding box para filtrar
            limit: Límite total de features por colección
            
        Returns:
            Diccionario con GeoDataFrames por colección
        """
        logger.info(f"Descargando colecciones del namespace: {namespace}")
        
        collections = self.get_collections()
        namespace_collections = [
            coll for coll in collections 
            if coll.id.startswith(f"{namespace}:")
        ]
        
        if not namespace_collections:
            logger.warning(f"No se encontraron colecciones para namespace: {namespace}")
            return {}
        
        results = {}
        for collection in namespace_collections:
            try:
                logger.info(f"Descargando {collection.id}...")
                gdf = self.download_features(
                    collection_id=collection.id,
                    bbox=bbox,
                    limit=limit
                )
                if not gdf.empty:
                    results[collection.id] = gdf
            except Exception as e:
                logger.error(f"Error descargando {collection.id}: {e}")
                continue
        
        logger.info(f"Descargadas {len(results)} colecciones de {namespace}")
        return results
    
    def get_collection_stats(self, collection_id: str) -> Dict:
        """
        Obtiene estadísticas básicas de una colección
        
        Args:
            collection_id: ID de la colección
            
        Returns:
            Estadísticas de la colección
        """
        try:
            # Descargar una pequeña muestra para obtener estadísticas
            sample = self.download_features(collection_id, limit=10, paginate=False)
            
            if sample.empty:
                return {"error": "No hay features disponibles"}
            
            # Obtener metadatos
            metadata = self.get_collection_metadata(collection_id)
            
            stats = {
                "collection_id": collection_id,
                "title": metadata.get("title", ""),
                "crs": str(sample.crs) if sample.crs else "unknown",
                "geometry_types": sample.geometry.geom_type.value_counts().to_dict(),
                "total_fields": len(sample.columns),
                "sample_size": len(sample),
                "extent": metadata.get("extent", {}),
                "description": metadata.get("description", "")
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"Error obteniendo estadísticas de {collection_id}: {e}")
            return {"error": str(e)}

# Función de conveniencia para testing
def test_client():
    """Función de prueba del cliente MAPAMA"""
    client = MAPAMAClient()
    
    try:
        # Listar colecciones
        collections = client.get_collections()
        print(f"Total colecciones: {len(collections)}")
        
        # Mostrar primeras 5
        for coll in collections[:5]:
            print(f"- {coll.id}: {coll.title}")
        
        # Obtener estadísticas de una colección
        if collections:
            stats = client.get_collection_stats(collections[0].id)
            print(f"\nEstadísticas de {collections[0].id}:")
            print(json.dumps(stats, indent=2, default=str))
            
    except Exception as e:
        print(f"Error en test: {e}")

if __name__ == "__main__":
    test_client()
