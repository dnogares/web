"""
Sincronizador de datos MAPAMA a PostGIS
Importa colecciones OGC Features como tablas espaciales con índices optimizados
"""

import logging
from typing import Optional, Dict, Any, List
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import SQLAlchemyError
import geopandas as gpd
from geoalchemy2 import Geometry
from geoalchemy2.shape import from_shape
import pandas as pd
from pathlib import Path
import json
from datetime import datetime

from ogc_client import MAPAMAClient

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MAPAMASyncer:
    """Sincronizador de datos MAPAMA con PostGIS"""
    
    def __init__(self, db_url: str):
        """
        Inicializa el sincronizador
        
        Args:
            db_url: URL de conexión a PostgreSQL
        """
        self.engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20
        )
        self.client = MAPAMAClient()
        
    def test_connection(self) -> bool:
        """Prueba la conexión a la base de datos"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT version()"))
                version = result.fetchone()[0]
                logger.info(f"Conexión exitosa a PostgreSQL: {version[:50]}...")
                return True
        except Exception as e:
            logger.error(f"Error de conexión: {e}")
            return False
    
    def create_sync_status_table(self):
        """Crea tabla de control de sincronización"""
        sql = """
        CREATE TABLE IF NOT EXISTS mapama_sync_status (
            id SERIAL PRIMARY KEY,
            collection_id VARCHAR(255) UNIQUE NOT NULL,
            table_name VARCHAR(255) NOT NULL,
            namespace VARCHAR(100),
            last_sync TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            feature_count INTEGER DEFAULT 0,
            bbox GEOMETRY(POLYGON, 25830),
            status VARCHAR(50) DEFAULT 'pending',
            error_message TEXT,
            metadata JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_sync_status_collection ON mapama_sync_status(collection_id);
        CREATE INDEX IF NOT EXISTS idx_sync_status_namespace ON mapama_sync_status(namespace);
        CREATE INDEX IF NOT EXISTS idx_sync_status_status ON mapama_sync_status(status);
        """
        
        try:
            with self.engine.connect() as conn:
                conn.execute(text(sql))
                conn.commit()
            logger.info("Tabla de control de sincronización creada/verificada")
        except Exception as e:
            logger.error(f"Error creando tabla de control: {e}")
            raise
    
    def get_table_name(self, collection_id: str) -> str:
        """
        Genera nombre de tabla para una colección
        
        Args:
            collection_id: ID de colección (ej: 'alimentacion:CDZ_Aceites')
            
        Returns:
            Nombre de tabla (ej: 'mapama_alimentacion_cdz_aceites')
        """
        # Reemplazar ':' por '_' y convertir a minúsculas
        table_name = collection_id.replace(':', '_').lower()
        # Añadir prefijo si no lo tiene
        if not table_name.startswith('mapama_'):
            table_name = f'mapama_{table_name}'
        return table_name
    
    def create_spatial_table(
        self,
        table_name: str,
        gdf: gpd.GeoDataFrame,
        collection_id: str
    ) -> bool:
        """
        Crea tabla espacial para la colección
        
        Args:
            table_name: Nombre de la tabla
            gdf: GeoDataFrame con los datos
            collection_id: ID de la colección
            
        Returns:
            True si exitoso
        """
        try:
            # Preparar columnas - eliminar geometría para procesarla aparte
            df = gdf.drop(columns=['geometry'])
            
            # Renombrar columnas problemáticas (caracteres especiales, espacios)
            df.columns = [col.lower().replace(' ', '_').replace('-', '_') 
                         for col in df.columns]
            
            # Convertir tipos de datos
            for col in df.columns:
                if df[col].dtype == 'object':
                    # Intentar convertir a JSON si es diccionario/lista
                    if df[col].apply(lambda x: isinstance(x, (dict, list))).any():
                        df[col] = df[col].apply(json.dumps)
                    else:
                        df[col] = df[col].astype(str)
            
            # Crear tabla sin geometría primero
            df.head(0).to_sql(
                table_name,
                self.engine,
                if_exists='replace',
                index=False,
                dtype={col: sqlalchemy.types.TEXT for col in df.columns}
            )
            
            # Añadir columna de geometría
            with self.engine.connect() as conn:
                geom_sql = f"""
                ALTER TABLE {table_name} 
                ADD COLUMN IF NOT EXISTS geom GEOMETRY(POLYGON, 25830);
                """
                conn.execute(text(geom_sql))
                conn.commit()
            
            logger.info(f"Tabla espacial {table_name} creada exitosamente")
            return True
            
        except Exception as e:
            logger.error(f"Error creando tabla {table_name}: {e}")
            return False
    
    def insert_geometries(self, table_name: str, gdf: gpd.GeoDataFrame) -> bool:
        """
        Inserta datos con geometrías en la tabla
        
        Args:
            table_name: Nombre de la tabla
            gdf: GeoDataFrame con datos
            
        Returns:
            True si exitoso
        """
        try:
            # Preparar datos
            df = gdf.drop(columns=['geometry'])
            df.columns = [col.lower().replace(' ', '_').replace('-', '_') 
                         for col in df.columns]
            
            # Convertir geometrías a WKT
            df['geom'] = gdf.geometry.apply(lambda x: x.wkt)
            
            # Insertar en lotes
            batch_size = 1000
            total_rows = len(df)
            
            for i in range(0, total_rows, batch_size):
                batch = df.iloc[i:i+batch_size]
                
                # Construir SQL de inserción
                columns = ', '.join(batch.columns)
                placeholders = ', '.join([f':{col}' for col in batch.columns])
                
                insert_sql = f"""
                INSERT INTO {table_name} ({columns})
                VALUES ({placeholders})
                """
                
                with self.engine.connect() as conn:
                    conn.execute(text(insert_sql), batch.to_dict('records'))
                    conn.commit()
                
                logger.info(f"Insertados {min(i+batch_size, total_rows)}/{total_rows} registros")
            
            logger.info(f"Datos insertados en {table_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error insertando datos en {table_name}: {e}")
            return False
    
    def create_spatial_index(self, table_name: str, geom_column: str = 'geom'):
        """
        Crea índice espacial GIST
        
        Args:
            table_name: Nombre de la tabla
            geom_column: Nombre de columna de geometría
        """
        try:
            index_name = f"idx_{table_name}_geom"
            
            sql = f"""
            CREATE INDEX IF NOT EXISTS {index_name} 
            ON {table_name} USING GIST({geom_column});
            """
            
            with self.engine.connect() as conn:
                conn.execute(text(sql))
                conn.commit()
            
            logger.info(f"Índice espacial creado: {index_name}")
            
        except Exception as e:
            logger.error(f"Error creando índice espacial: {e}")
    
    def create_attribute_indexes(self, table_name: str, gdf: gpd.GeoDataFrame):
        """
        Crea índices en atributos comunes
        
        Args:
            table_name: Nombre de la tabla
            gdf: GeoDataFrame para inferir columnas importantes
        """
        try:
            # Columnas comunes para indexar
            common_columns = ['nombre', 'codigo', 'id', 'name', 'code', 'tipo', 'type']
            table_columns = [col.lower() for col in gdf.columns if col.lower() != 'geometry']
            
            for col in common_columns:
                if col in table_columns:
                    index_name = f"idx_{table_name}_{col}"
                    sql = f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name}({col});"
                    
                    with self.engine.connect() as conn:
                        conn.execute(text(sql))
                        conn.commit()
                    
                    logger.info(f"Índice de atributo creado: {index_name}")
                    
        except Exception as e:
            logger.error(f"Error creando índices de atributos: {e}")
    
    def optimize_table(self, table_name: str):
        """
        Optimiza tabla con VACUUM ANALYZE
        
        Args:
            table_name: Nombre de la tabla
        """
        try:
            with self.engine.connect() as conn:
                conn.execute(text(f"VACUUM ANALYZE {table_name};"))
                conn.commit()
            
            logger.info(f"Tabla {table_name} optimizada")
            
        except Exception as e:
            logger.error(f"Error optimizando tabla {table_name}: {e}")
    
    def update_sync_status(
        self,
        collection_id: str,
        table_name: str,
        status: str,
        feature_count: int = 0,
        bbox: str = None,
        error_message: str = None,
        metadata: Dict = None
    ):
        """
        Actualiza estado de sincronización
        
        Args:
            collection_id: ID de la colección
            table_name: Nombre de la tabla
            status: Estado ('synced', 'error', 'pending')
            feature_count: Número de features
            bbox: Bounding box en WKT
            error_message: Mensaje de error si aplica
            metadata: Metadatos adicionales
        """
        try:
            # Extraer namespace del collection_id
            namespace = collection_id.split(':')[0] if ':' in collection_id else None
            
            sql = """
            INSERT INTO mapama_sync_status 
            (collection_id, table_name, namespace, last_sync, feature_count, bbox, status, error_message, metadata, updated_at)
            VALUES (:collection_id, :table_name, :namespace, :last_sync, :feature_count, 
                    ST_GeomFromText(:bbox, 25830), :status, :error_message, :metadata, :updated_at)
            ON CONFLICT (collection_id) 
            DO UPDATE SET 
                last_sync = EXCLUDED.last_sync,
                feature_count = EXCLUDED.feature_count,
                bbox = EXCLUDED.bbox,
                status = EXCLUDED.status,
                error_message = EXCLUDED.error_message,
                metadata = EXCLUDED.metadata,
                updated_at = EXCLUDED.updated_at;
            """
            
            params = {
                'collection_id': collection_id,
                'table_name': table_name,
                'namespace': namespace,
                'last_sync': datetime.now(),
                'feature_count': feature_count,
                'bbox': bbox,
                'status': status,
                'error_message': error_message,
                'metadata': json.dumps(metadata) if metadata else None,
                'updated_at': datetime.now()
            }
            
            with self.engine.connect() as conn:
                conn.execute(text(sql), params)
                conn.commit()
                
        except Exception as e:
            logger.error(f"Error actualizando estado de sincronización: {e}")
    
    def sync_collection(
        self,
        collection_id: str,
        bbox: Optional[tuple] = None,
        update_strategy: str = 'replace',
        limit: Optional[int] = None
    ) -> bool:
        """
        Sincroniza una colección MAPAMA a PostGIS
        
        Args:
            collection_id: ID de la colección
            bbox: Bounding box (minx, miny, maxx, maxy)
            update_strategy: 'replace', 'append', 'upsert'
            limit: Límite de features a descargar
            
        Returns:
            True si exitoso
        """
        logger.info(f"Iniciando sincronización de {collection_id}")
        
        try:
            # Actualizar estado a 'syncing'
            table_name = self.get_table_name(collection_id)
            self.update_sync_status(collection_id, table_name, 'syncing')
            
            # Descargar datos
            gdf = self.client.download_features(
                collection_id=collection_id,
                bbox=bbox,
                limit=limit,
                target_crs="EPSG:25830"
            )
            
            if gdf.empty:
                logger.warning(f"No hay datos para {collection_id}")
                self.update_sync_status(
                    collection_id, table_name, 'error', 
                    error_message="No hay datos disponibles"
                )
                return False
            
            # Crear/actualizar tabla
            if update_strategy == 'replace' or not inspect(self.engine).has_table(table_name):
                if not self.create_spatial_table(table_name, gdf, collection_id):
                    raise Exception("Error creando tabla espacial")
            
            # Insertar datos
            if not self.insert_geometries(table_name, gdf):
                raise Exception("Error insertando datos")
            
            # Crear índices
            self.create_spatial_index(table_name)
            self.create_attribute_indexes(table_name, gdf)
            
            # Optimizar tabla
            self.optimize_table(table_name)
            
            # Calcular bbox de los datos
            bounds = gdf.total_bounds
            bbox_wkt = f"POLYGON(({bounds[0]} {bounds[1]}, {bounds[2]} {bounds[1]}, {bounds[2]} {bounds[3]}, {bounds[0]} {bounds[3]}, {bounds[0]} {bounds[1]}))"
            
            # Obtener metadatos
            metadata = self.client.get_collection_metadata(collection_id)
            
            # Actualizar estado final
            self.update_sync_status(
                collection_id=collection_id,
                table_name=table_name,
                status='synced',
                feature_count=len(gdf),
                bbox=bbox_wkt,
                metadata=metadata
            )
            
            logger.info(f"Sincronización completada: {collection_id} ({len(gdf)} features)")
            return True
            
        except Exception as e:
            logger.error(f"Error en sincronización de {collection_id}: {e}")
            self.update_sync_status(
                collection_id=collection_id,
                table_name=table_name,
                status='error',
                error_message=str(e)
            )
            return False
    
    def sync_namespace(
        self,
        namespace: str,
        bbox: Optional[tuple] = None,
        limit: Optional[int] = None
    ) -> Dict[str, bool]:
        """
        Sincroniza todas las colecciones de un namespace
        
        Args:
            namespace: Namespace (ej: 'biodiversidad')
            bbox: Bounding box para filtrar
            limit: Límite por colección
            
        Returns:
            Diccionario con resultados por colección
        """
        logger.info(f"Sincronizando namespace: {namespace}")
        
        results = {}
        
        try:
            # Obtener colecciones del namespace
            collections = self.client.get_collections()
            namespace_collections = [
                coll for coll in collections 
                if coll.id.startswith(f"{namespace}:")
            ]
            
            if not namespace_collections:
                logger.warning(f"No hay colecciones para namespace: {namespace}")
                return results
            
            # Sincronizar cada colección
            for collection in namespace_collections:
                try:
                    success = self.sync_collection(
                        collection.id,
                        bbox=bbox,
                        limit=limit
                    )
                    results[collection.id] = success
                    
                except Exception as e:
                    logger.error(f"Error sincronizando {collection.id}: {e}")
                    results[collection.id] = False
            
            successful = sum(results.values())
            logger.info(f"Sincronización namespace {namespace}: {successful}/{len(results)} exitosas")
            
        except Exception as e:
            logger.error(f"Error en sincronización de namespace {namespace}: {e}")
        
        return results
    
    def get_sync_status(self, collection_id: str = None, namespace: str = None) -> List[Dict]:
        """
        Obtiene estado de sincronización
        
        Args:
            collection_id: ID específico de colección
            namespace: Namespace específico
            
        Returns:
            Lista de estados
        """
        try:
            sql = "SELECT * FROM mapama_sync_status WHERE 1=1"
            params = {}
            
            if collection_id:
                sql += " AND collection_id = :collection_id"
                params['collection_id'] = collection_id
            
            if namespace:
                sql += " AND namespace = :namespace"
                params['namespace'] = namespace
            
            sql += " ORDER BY last_sync DESC"
            
            with self.engine.connect() as conn:
                result = conn.execute(text(sql), params)
                return [dict(row._mapping) for row in result]
                
        except Exception as e:
            logger.error(f"Error obteniendo estado de sincronización: {e}")
            return []

# Importar sqlalchemy para tipos
import sqlalchemy
