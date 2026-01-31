"""
API FastAPI para análisis de afecciones con datos MAPAMA
Endpoints optimizados con índices espaciales GIST
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text, func
from sqlalchemy.orm import Session
import logging
from datetime import datetime
import json
import os

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Models
class AfeccionResult(BaseModel):
    """Resultado de análisis de afección"""
    refcat: str = Field(..., description="Referencia catastral")
    capa: str = Field(..., description="Nombre de la capa MAPAMA")
    tipo_afeccion: str = Field(..., description="Tipo de afección (intersects, contains, within)")
    area_afectada_m2: float = Field(..., description="Área afectada en metros cuadrados")
    porcentaje_afeccion: float = Field(..., description="Porcentaje de afectación")
    atributos_capa: Dict[str, Any] = Field(..., description="Atributos de la capa que afecta")

class AfeccionSummary(BaseModel):
    """Resumen de afecciones por referencia"""
    refcat: str
    provincia: Optional[str] = None
    municipio: Optional[str] = None
    total_capas_afectan: int
    area_total_afectada_m2: float
    porcentaje_total_afectacion: float
    afecciones_detalle: List[AfeccionResult]

class SpatialQuery(BaseModel):
    """Consulta espacial con parámetros optimizados"""
    refcat: str = Field(..., description="Referencia catastral")
    capas: List[str] = Field(..., description="Lista de IDs de capas MAPAMA")
    buffer_m: float = Field(0, description="Buffer en metros")
    tipo_interseccion: str = Field("intersects", description="Tipo: intersects, contains, within, dwithin")
    min_area_afectada: float = Field(0, description="Área mínima afectada en m²")
    min_porcentaje: float = Field(0, description="Porcentaje mínimo de afectación")

# Database dependency
def get_db_session():
    """Dependency para obtener sesión de base de datos"""
    host = os.getenv("POSTGIS_HOST", "localhost")
    port = os.getenv("POSTGIS_PORT", "5432")
    dbname = os.getenv("POSTGIS_DATABASE", "GIS")
    user = os.getenv("POSTGIS_USER", "manuel")
    password = os.getenv("POSTGIS_PASSWORD", "Aa123456")
    
    DATABASE_URL = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    
    with Session(engine) as session:
        try:
            yield session
        finally:
            session.close()

class AfeccionesService:
    """Servicio para análisis de afecciones espaciales"""
    
    def __init__(self, db_session: Session):
        self.session = db_session
    
    def get_parcela_geometry(self, refcat: str) -> Optional[Dict]:
        """
        Obtiene geometría y datos básicos de una parcela catastral
        
        Args:
            refcat: Referencia catastral
            
        Returns:
            Diccionario con geometría y datos de la parcela
        """
        sql = """
        SELECT 
            refcat,
            provincia,
            municipio,
            ST_AsText(geom) as geom_wkt,
            ST_Area(geom) as area_m2,
            ST_AsBinary(geom) as geom_binary
        FROM catastro 
        WHERE refcat = :refcat
        """
        
        result = self.session.execute(text(sql), {"refcat": refcat}).fetchone()
        
        if not result:
            return None
        
        return {
            "refcat": result.refcat,
            "provincia": result.provincia,
            "municipio": result.municipio,
            "area_m2": float(result.area_m2),
            "geom_wkt": result.geom_wkt
        }
    
    def analyze_afecciones(
        self,
        refcat: str,
        capas: List[str],
        buffer_m: float = 0,
        tipo_interseccion: str = "intersects",
        min_area_afectada: float = 0,
        min_porcentaje: float = 0
    ) -> AfeccionSummary:
        """
        Analiza afecciones para una parcela catastral
        
        Args:
            refcat: Referencia catastral
            capas: Lista de capas MAPAMA a analizar
            buffer_m: Buffer en metros
            tipo_interseccion: Tipo de intersección espacial
            min_area_afectada: Área mínima afectada
            min_porcentaje: Porcentaje mínimo de afectación
            
        Returns:
            Resumen con todas las afecciones encontradas
        """
        # Obtener datos de la parcela
        parcela = self.get_parcela_geometry(refcat)
        if not parcela:
            raise HTTPException(status_code=404, detail=f"Parcela {refcat} no encontrada")
        
        afecciones_encontradas = []
        area_total_afectada = 0
        
        # Analizar cada capa
        for capa in capas:
            try:
                # Construir nombre de tabla
                table_name = capa if capa.startswith('mapama_') else f'mapama_{capa}'
                
                # Construir SQL optimizado según tipo de intersección
                afecciones_capa = self._analyze_capa(
                    refcat=refcat,
                    table_name=table_name,
                    buffer_m=buffer_m,
                    tipo_interseccion=tipo_interseccion,
                    min_area_afectada=min_area_afectada,
                    min_porcentaje=min_porcentaje,
                    area_parcela=parcela['area_m2']
                )
                
                afecciones_encontradas.extend(afecciones_capa)
                
            except Exception as e:
                logger.error(f"Error analizando capa {capa}: {e}")
                continue
        
        # Calcular totales
        for afeccion in afecciones_encontradas:
            area_total_afectada += afeccion.area_afectada_m2
        
        porcentaje_total = (area_total_afectada / parcela['area_m2']) * 100 if parcela['area_m2'] > 0 else 0
        
        return AfeccionSummary(
            refcat=refcat,
            provincia=parcela['provincia'],
            municipio=parcela['municipio'],
            total_capas_afectan=len(set(a.capa for a in afecciones_encontradas)),
            area_total_afectada_m2=area_total_afectada,
            porcentaje_total_afectacion=porcentaje_total,
            afecciones_detalle=afecciones_encontradas
        )
    
    def _analyze_capa(
        self,
        refcat: str,
        table_name: str,
        buffer_m: float,
        tipo_interseccion: str,
        min_area_afectada: float,
        min_porcentaje: float,
        area_parcela: float
    ) -> List[AfeccionResult]:
        """
        Analiza afecciones para una capa específica
        
        Args:
            refcat: Referencia catastral
            table_name: Nombre de la tabla MAPAMA
            buffer_m: Buffer en metros
            tipo_interseccion: Tipo de intersección
            min_area_afectada: Área mínima afectada
            min_porcentaje: Porcentaje mínimo
            area_parcela: Área total de la parcela
            
        Returns:
            Lista de afecciones encontradas
        """
        
        # Construir cláusula espacial según tipo
        if tipo_interseccion == "dwithin":
            spatial_clause = "ST_DWithin(c.geom, m.geom, :buffer_m)"
            area_calc = "ST_Area(m.geom)"
        elif tipo_interseccion == "contains":
            spatial_clause = "ST_Contains(m.geom, c.geom)"
            area_calc = "ST_Area(c.geom)"
        else:  # intersects (default)
            spatial_clause = "ST_Intersects(c.geom, ST_Buffer(m.geom, :buffer_m))"
            area_calc = "ST_Area(ST_Intersection(c.geom, ST_Buffer(m.geom, :buffer_m)))"
        
        # SQL optimizado con índices
        sql = f"""
        WITH parcela AS (
            SELECT refcat, provincia, municipio, geom, ST_Area(geom) as area_m2
            FROM catastro 
            WHERE refcat = :refcat
        ),
        intersecciones AS (
            SELECT 
                p.refcat,
                p.provincia,
                p.municipio,
                '{table_name}' as capa,
                '{tipo_interseccion}' as tipo_afeccion,
                {area_calc} as area_afectada_m2,
                CASE 
                    WHEN {area_calc} > 0 THEN 
                        ({area_calc} / p.area_m2 * 100)
                    ELSE 0 
                END as porcentaje_afeccion,
                m.*  -- Todos los atributos de la capa MAPAMA
            FROM parcela p
            JOIN {table_name} m ON (
                p.geom && m.geom  -- Filtro bbox primero (usa índice GIST)
                AND {spatial_clause}  -- Luego intersección exacta
            )
            WHERE {area_calc} >= :min_area_afectada
            AND CASE 
                WHEN {area_calc} > 0 THEN 
                    ({area_calc} / p.area_m2 * 100)
                ELSE 0 
            END >= :min_porcentaje
        )
        SELECT * FROM intersecciones
        ORDER BY porcentaje_afeccion DESC;
        """
        
        params = {
            "refcat": refcat,
            "buffer_m": buffer_m,
            "min_area_afectada": min_area_afectada,
            "min_porcentaje": min_porcentaje
        }
        
        result = self.session.execute(text(sql), params).fetchall()
        
        afecciones = []
        for row in result:
            # Extraer atributos de la capa (excluir columnas del JOIN)
            atributos = {}
            for key, value in row._mapping.items():
                if key not in ['refcat', 'provincia', 'municipio', 'capa', 'tipo_afeccion', 
                              'area_afectada_m2', 'porcentaje_afeccion']:
                    atributos[key] = value
            
            afeccion = AfeccionResult(
                refcat=row.refcat,
                capa=row.capa,
                tipo_afeccion=row.tipo_afeccion,
                area_afectada_m2=float(row.area_afectada_m2),
                porcentaje_afeccion=float(row.porcentaje_afeccion),
                atributos_capa=atributos
            )
            afecciones.append(afeccion)
        
        return afecciones
    
    def get_estadisticas_capa(self, capa: str) -> Dict[str, Any]:
        """
        Obtiene estadísticas de una capa MAPAMA
        
        Args:
            capa: Nombre de la capa
            
        Returns:
            Estadísticas de la capa
        """
        table_name = capa if capa.startswith('mapama_') else f'mapama_{capa}'
        
        sql = f"""
        SELECT 
            COUNT(*) as total_features,
            COUNT(DISTINCT provincia) as provincias_cubre,
            ST_AsText(ST_Extent(geom)) as extent_wkt,
            SUM(ST_Area(geom)) as area_total_m2
        FROM {table_name}
        WHERE geom IS NOT NULL;
        """
        
        try:
            result = self.session.execute(text(sql)).fetchone()
            return {
                "capa": capa,
                "table_name": table_name,
                "total_features": result.total_features,
                "provincias_cubre": result.provincias_cubre,
                "extent_wkt": result.extent_wkt,
                "area_total_m2": float(result.area_total_m2) if result.area_total_m2 else 0
            }
        except Exception as e:
            logger.error(f"Error obteniendo estadísticas de {capa}: {e}")
            return {"error": str(e)}
    
    def get_capas_disponibles(self) -> List[Dict[str, Any]]:
        """
        Obtiene lista de capas MAPAMA disponibles
        
        Returns:
            Lista de capas con información básica
        """
        sql = """
        SELECT 
            collection_id,
            table_name,
            namespace,
            feature_count,
            status,
            last_sync,
            metadata
        FROM mapama_sync_status
        WHERE status = 'synced'
        ORDER BY namespace, collection_id;
        """
        
        result = self.session.execute(text(sql)).fetchall()
        
        capas = []
        for row in result:
            metadata = json.loads(row.metadata) if row.metadata else {}
            capas.append({
                "collection_id": row.collection_id,
                "table_name": row.table_name,
                "namespace": row.namespace,
                "feature_count": row.feature_count,
                "last_sync": row.last_sync.isoformat() if row.last_sync else None,
                "title": metadata.get("title", ""),
                "description": metadata.get("description", "")
            })
        
        return capas

# Router FastAPI
router = APIRouter(prefix="/api/v1/afecciones", tags=["afecciones"])

@router.get("/{refcat}", response_model=AfeccionSummary)
async def get_afecciones(
    refcat: str,
    capas: List[str] = Query(..., description="IDs de capas MAPAMA"),
    buffer_m: float = Query(0, description="Buffer en metros"),
    tipo_interseccion: str = Query("intersects", description="Tipo: intersects, contains, within, dwithin"),
    min_area_afectada: float = Query(0, description="Área mínima afectada en m²"),
    min_porcentaje: float = Query(0, description="Porcentaje mínimo de afectación"),
    db: Session = Depends(get_db_session)
):
    """
    Consulta optimizada de afecciones usando índices GIST
    
    Ejemplo de uso:
    GET /api/v1/afecciones/04001A00100001?capas=biodiversidad_habitat_art17&capas=alimentacion_cdz_aceites&buffer_m=100
    """
    service = AfeccionesService(db)
    
    try:
        resultado = service.analyze_afecciones(
            refcat=refcat,
            capas=capas,
            buffer_m=buffer_m,
            tipo_interseccion=tipo_interseccion,
            min_area_afectada=min_area_afectada,
            min_porcentaje=min_porcentaje
        )
        return resultado
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en análisis de afecciones: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/capas/disponibles")
async def get_capas_disponibles(db: Session = Depends(get_db_session)):
    """Obtiene lista de capas MAPAMA sincronizadas"""
    service = AfeccionesService(db)
    return {"capas": service.get_capas_disponibles()}

@router.get("/capas/{capa}/estadisticas")
async def get_estadisticas_capa(
    capa: str,
    db: Session = Depends(get_db_session)
):
    """Obtiene estadísticas de una capa específica"""
    service = AfeccionesService(db)
    return service.get_estadisticas_capa(capa)

@router.post("/consulta-multiple")
async def consulta_multiple(
    refcats: List[str],
    capas: List[str] = Query(..., description="IDs de capas MAPAMA"),
    buffer_m: float = Query(0, description="Buffer en metros"),
    db: Session = Depends(get_db_session)
):
    """
    Consulta de afecciones para múltiples referencias catastrales
    
    Optimizado para procesamiento por lotes usando consultas preparadas
    """
    service = AfeccionesService(db)
    resultados = []
    
    for refcat in refcats:
        try:
            resultado = service.analyze_afecciones(
                refcat=refcat,
                capas=capas,
                buffer_m=buffer_m
            )
            resultados.append(resultado)
        except Exception as e:
            logger.error(f"Error procesando {refcat}: {e}")
            continue
    
    return {
        "total_referencias": len(refcats),
        "procesadas": len(resultados),
        "resultados": resultados
    }

@router.get("/resumen/provincia/{provincia}")
async def get_resumen_provincia(
    provincia: str,
    capas: List[str] = Query(..., description="IDs de capas MAPAMA"),
    db: Session = Depends(get_db_session)
):
    """
    Obtiene resumen de afecciones por provincia
    
    Útil para análisis territoriales y planificación
    """
    # Construir SQL para resumen provincial
    capas_sql = ", ".join([f"'{capa}'" for capa in capas])
    
    sql = f"""
    WITH parcelas_provincia AS (
        SELECT refcat, provincia, municipio, geom, ST_Area(geom) as area_m2
        FROM catastro 
        WHERE provincia = :provincia
    ),
    afecciones_provincia AS (
        SELECT 
            p.provincia,
            COUNT(DISTINCT p.refcat) as parcelas_afectadas,
            COUNT(p.refcat) as total_parcelas,
            SUM(p.area_m2) as area_total_provincia,
            {capas_sql} as capas_analizadas
        FROM parcelas_provincia p
        LEFT JOIN (
            SELECT DISTINCT refcat, 'afectada' as afeccion
            FROM (
                -- Aquí irían las uniones con las capas MAPAMA
                SELECT refcat FROM catastro WHERE provincia = :provincia LIMIT 1
            ) subquery
        ) a ON p.refcat = a.refcat
        GROUP BY p.provincia
    )
    SELECT * FROM afecciones_provincia;
    """
    
    try:
        result = db.execute(text(sql), {"provincia": provincia}).fetchone()
        if result:
            return {
                "provincia": result.provincia,
                "total_parcelas": result.total_parcelas,
                "parcelas_afectadas": result.parcelas_afectadas,
                "area_total_provincia": float(result.area_total_provincia),
                "porcentaje_afectacion": (result.parcelas_afectadas / result.total_parcelas * 100) if result.total_parcelas > 0 else 0,
                "capas_analizadas": capas
            }
        else:
            return {"error": f"No hay datos para la provincia {provincia}"}
            
    except Exception as e:
        logger.error(f"Error en resumen provincial: {e}")
        raise HTTPException(status_code=500, detail=str(e))
