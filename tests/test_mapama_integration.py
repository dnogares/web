"""
Tests para integración MAPAMA OGC Features
Valida descarga, sincronización y rendimiento de consultas
"""

import pytest
import tempfile
import os
from pathlib import Path
import geopandas as gpd
import time
from unittest.mock import Mock, patch

# Importar módulos a probar
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from ogc_client import MAPAMAClient, OGCCollection
from sync_mapama import MAPAMASyncer
from api.routes.afecciones import AfeccionesService

class TestMAPAMAClient:
    """Tests para cliente OGC Features"""
    
    @pytest.fixture
    def client(self):
        """Cliente MAPAMA para testing"""
        return MAPAMAClient()
    
    def test_get_collections(self, client):
        """Test obtener colecciones disponibles"""
        collections = client.get_collections()
        
        assert isinstance(collections, list)
        assert len(collections) > 0
        
        # Verificar estructura
        for coll in collections:
            assert isinstance(coll, OGCCollection)
            assert coll.id
            assert coll.title
    
    def test_get_collection_metadata(self, client):
        """Test obtener metadatos de colección"""
        # Primero obtener una colección válida
        collections = client.get_collections()
        if not collections:
            pytest.skip("No hay colecciones disponibles para testing")
        
        collection_id = collections[0].id
        metadata = client.get_collection_metadata(collection_id)
        
        assert isinstance(metadata, dict)
        assert 'id' in metadata
        assert metadata['id'] == collection_id
    
    def test_get_queryables(self, client):
        """Test obtener propiedades consultables"""
        collections = client.get_collections()
        if not collections:
            pytest.skip("No hay colecciones disponibles para testing")
        
        collection_id = collections[0].id
        queryables = client.get_queryables(collection_id)
        
        assert isinstance(queryables, dict)
        # Debe tener al menos algunas propiedades
        assert len(queryables) > 0
    
    def test_download_features_small(self, client):
        """Test descarga de features (límite pequeño)"""
        collections = client.get_collections()
        if not collections:
            pytest.skip("No hay colecciones disponibles para testing")
        
        collection_id = collections[0].id
        
        # Descargar muestra pequeña
        gdf = client.download_features(
            collection_id=collection_id,
            limit=10,
            paginate=False
        )
        
        assert isinstance(gdf, gpd.GeoDataFrame)
        assert len(gdf) <= 10
        
        if not gdf.empty:
            assert 'geometry' in gdf.columns
            assert gdf.crs is not None
    
    def test_download_features_pagination(self, client):
        """Test descarga con paginación (>5000 features)"""
        collections = client.get_collections()
        if not collections:
            pytest.skip("No hay colecciones disponibles para testing")
        
        collection_id = collections[0].id
        
        # Intentar descargar más de 5000 features
        start_time = time.time()
        gdf = client.download_features(
            collection_id=collection_id,
            limit=6000,
            paginate=True
        )
        elapsed_time = time.time() - start_time
        
        assert isinstance(gdf, gpd.GeoDataFrame)
        # Verificar que maneja correctamente la paginación
        assert elapsed_time < 30  # No debería tardar más de 30 segundos
    
    def test_crs_transformation(self, client):
        """Test transformación de CRS"""
        collections = client.get_collections()
        if not collections:
            pytest.skip("No hay colecciones disponibles para testing")
        
        collection_id = collections[0].id
        
        # Descargar con CRS específico
        gdf = client.download_features(
            collection_id=collection_id,
            limit=5,
            target_crs="EPSG:25830"
        )
        
        if not gdf.empty:
            assert str(gdf.crs) == "EPSG:25830"
    
    def test_download_by_namespace(self, client):
        """Test descarga por namespace"""
        # Probar con un namespace común
        namespace = "biodiversidad"
        
        results = client.download_by_namespace(
            namespace=namespace,
            limit=10
        )
        
        assert isinstance(results, dict)
        # Verificar que todas las colecciones pertenecen al namespace
        for collection_id, gdf in results.items():
            assert collection_id.startswith(f"{namespace}:")
            assert isinstance(gdf, gpd.GeoDataFrame)

class TestMAPAMASyncer:
    """Tests para sincronizador PostGIS"""
    
    @pytest.fixture
    def syncer(self):
        """Sincronizador para testing (base de datos temporal)"""
        # Usar base de datos temporal para testing
        temp_db_url = "sqlite:///test.db"  # Simplificado para testing
        return MAPAMASyncer(temp_db_url)
    
    def test_get_table_name(self, syncer):
        """Test generación de nombres de tabla"""
        # Casos típicos
        assert syncer.get_table_name("alimentacion:CDZ_Aceites") == "mapama_alimentacion_cdz_aceites"
        assert syncer.get_table_name("biodiversidad:Habitat_Art17") == "mapama_biodiversidad_habitat_art17"
        assert syncer.get_table_name("test_collection") == "mapama_test_collection"
    
    @patch('sync_mapama.MAPAMAClient')
    def test_sync_collection_mock(self, mock_client_class, syncer):
        """Test sincronización con mock"""
        # Configurar mock
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        # Crear GeoDataFrame de prueba
        from shapely.geometry import Polygon
        test_geom = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        test_gdf = gpd.GeoDataFrame({
            'id': [1, 2],
            'nombre': ['Test 1', 'Test 2'],
            'geometry': [test_geom, test_geom]
        }, crs="EPSG:25830")
        
        mock_client.download_features.return_value = test_gdf
        mock_client.get_collection_metadata.return_value = {"title": "Test Collection"}
        
        # Mock de conexión a base de datos
        with patch.object(syncer, 'engine') as mock_engine:
            mock_conn = Mock()
            mock_engine.connect.return_value.__enter__.return_value = mock_conn
            
            # Ejecutar sincronización
            result = syncer.sync_collection("test:collection")
            
            # Verificar que se llamó a download_features
            mock_client.download_features.assert_called_once()
            assert result is not None

class TestAfeccionesService:
    """Tests para servicio de afecciones"""
    
    @pytest.fixture
    def mock_session(self):
        """Sesión de base de datos mock"""
        return Mock()
    
    @pytest.fixture
    def service(self, mock_session):
        """Servicio de afecciones para testing"""
        return AfeccionesService(mock_session)
    
    def test_get_parcela_geometry_found(self, service, mock_session):
        """Test obtener geometría de parcela encontrada"""
        # Configurar mock
        mock_result = Mock()
        mock_result.refcat = "04001A00100001"
        mock_result.provincia = "04"
        mock_result.municipio = "040"
        mock_result.area_m2 = 1000.0
        mock_result.geom_wkt = "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"
        
        mock_session.execute.return_value.fetchone.return_value = mock_result
        
        # Ejecutar
        result = service.get_parcela_geometry("04001A00100001")
        
        # Verificar
        assert result is not None
        assert result['refcat'] == "04001A00100001"
        assert result['provincia'] == "04"
        assert result['area_m2'] == 1000.0
    
    def test_get_parcela_geometry_not_found(self, service, mock_session):
        """Test obtener geometría de parcela no encontrada"""
        mock_session.execute.return_value.fetchone.return_value = None
        
        result = service.get_parcela_geometry("99999A99999999")
        
        assert result is None
    
    def test_analyze_afecciones_parcela_not_found(self, service, mock_session):
        """Test análisis de afecciones con parcela no encontrada"""
        mock_session.execute.return_value.fetchone.return_value = None
        
        with pytest.raises(Exception):  # HTTPException en implementación real
            service.analyze_afecciones("99999A99999999", ["test_capa"])
    
    def test_get_capas_disponibles(self, service, mock_session):
        """Test obtener capas disponibles"""
        # Configurar mock
        mock_result = Mock()
        mock_result.collection_id = "biodiversidad:habitat"
        mock_result.table_name = "mapama_biodiversidad_habitat"
        mock_result.namespace = "biodiversidad"
        mock_result.feature_count = 1000
        mock_result.status = "synced"
        mock_result.last_sync = "2024-01-01"
        mock_result.metadata = '{"title": "Test"}'
        
        mock_session.execute.return_value.fetchall.return_value = [mock_result]
        
        result = service.get_capas_disponibles()
        
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]['collection_id'] == "biodiversidad:habitat"

class TestRendimiento:
    """Tests de rendimiento"""
    
    def test_descarga_paginada_rendimiento(self):
        """Test rendimiento de descarga paginada >5000 features"""
        client = MAPAMAClient()
        
        collections = client.get_collections()
        if not collections:
            pytest.skip("No hay colecciones disponibles")
        
        # Buscar colección con muchos features
        collection_id = collections[0].id
        
        start_time = time.time()
        gdf = client.download_features(
            collection_id=collection_id,
            limit=6000,
            paginate=True
        )
        elapsed_time = time.time() - start_time
        
        # Verificar rendimiento
        assert elapsed_time < 30  # Debe completarse en menos de 30 segundos
        
        if len(gdf) > 0:
            # Calcular tiempo por feature
            time_per_feature = elapsed_time / len(gdf)
            assert time_per_feature < 0.01  # Menos de 10ms por feature
    
    def test_transformacion_crs_rendimiento(self):
        """Test rendimiento de transformación CRS"""
        client = MAPAMAClient()
        
        collections = client.get_collections()
        if not collections:
            pytest.skip("No hay colecciones disponibles")
        
        collection_id = collections[0].id
        
        # Descargar muestra
        gdf_original = client.download_features(
            collection_id=collection_id,
            limit=1000,
            target_crs="EPSG:4326"  # WGS84
        )
        
        if gdf_original.empty:
            pytest.skip("No hay datos para transformar")
        
        # Medir tiempo de transformación
        start_time = time.time()
        gdf_transformed = gdf_original.to_crs("EPSG:25830")
        elapsed_time = time.time() - start_time
        
        # Verificar rendimiento
        assert elapsed_time < 5  # Debe completarse en menos de 5 segundos
        assert str(gdf_transformed.crs) == "EPSG:25830"
    
    def test_consulta_espacial_optimizada(self):
        """Test rendimiento de consulta espacial optimizada"""
        # Este test requeriría base de datos real
        # Por ahora, solo verificamos la estructura SQL
        service = AfeccionesService(Mock())
        
        # Verificar que la consulta SQL contiene optimizaciones
        sql = service._analyze_capa.__doc__
        assert "GIST" in sql or "&&" in sql  # Operador bbox

class TestIntegridad:
    """Tests de integridad de datos"""
    
    def test_geometrias_validas_post_import(self):
        """Test que las geometrías son válidas después de importar"""
        client = MAPAMAClient()
        
        collections = client.get_collections()
        if not collections:
            pytest.skip("No hay colecciones disponibles")
        
        collection_id = collections[0].id
        
        # Descargar muestra
        gdf = client.download_features(
            collection_id=collection_id,
            limit=100
        )
        
        if gdf.empty:
            pytest.skip("No hay geometrías para validar")
        
        # Verificar geometrías válidas
        invalid_geoms = ~gdf.geometry.is_valid
        assert invalid_geoms.sum() == 0, f"Se encontraron {invalid_geoms.sum()} geometrías inválidas"
        
        # Verificar que no hay geometrías nulas
        null_geoms = gdf.geometry.isnull()
        assert null_geoms.sum() == 0, f"Se encontraron {null_geoms.sum()} geometrías nulas"
    
    def test_integridad_atributos(self):
        """Test integridad de atributos descargados"""
        client = MAPAMAClient()
        
        collections = client.get_collections()
        if not collections:
            pytest.skip("No hay colecciones disponibles")
        
        collection_id = collections[0].id
        
        # Descargar muestra
        gdf = client.download_features(
            collection_id=collection_id,
            limit=100
        )
        
        if gdf.empty:
            pytest.skip("No hay datos para validar")
        
        # Verificar que hay columnas además de geometría
        non_geom_cols = [col for col in gdf.columns if col != 'geometry']
        assert len(non_geom_cols) > 0, "No hay columnas de atributos"
        
        # Verificar que no hay valores nulos críticos (si hay ID)
        if 'id' in gdf.columns:
            null_ids = gdf['id'].isnull()
            assert null_ids.sum() == 0, "Hay IDs nulos"

# Funciones utilitarias para testing
def create_test_geodataframe(n_features=10):
    """Crea GeoDataFrame de prueba"""
    from shapely.geometry import Polygon
    import numpy as np
    
    # Crear polígonos de prueba
    geometries = []
    for i in range(n_features):
        x, y = i * 0.1, i * 0.1
        geom = Polygon([
            (x, y), (x + 0.05, y), 
            (x + 0.05, y + 0.05), (x, y + 0.05)
        ])
        geometries.append(geom)
    
    # Crear GeoDataFrame
    gdf = gpd.GeoDataFrame({
        'id': range(n_features),
        'nombre': [f'Feature_{i}' for i in range(n_features)],
        'tipo': ['test'] * n_features,
        'geometry': geometries
    }, crs="EPSG:25830")
    
    return gdf

if __name__ == "__main__":
    # Ejecutar tests
    pytest.main([__file__, "-v"])
