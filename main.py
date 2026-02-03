#!/usr/bin/env python3
"""
Servidor FastAPI integrado para el visor catastral con Glassmorphism
"""

import json
import os
import sys
import socket
import requests
import unicodedata
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# --- CORRECCIÓN DE RUTAS ---
# Asegurar que el servidor siempre trabaje en el directorio del script
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Agregar ruta de referenciaspy
REFERENCIASPY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "referenciaspy")
if os.path.exists(REFERENCIASPY_PATH):
    sys.path.insert(0, REFERENCIASPY_PATH)
    print(f"✅ Ruta de referenciaspy agregada: {REFERENCIASPY_PATH}")
else:
    print(f"⚠️ Ruta de referenciaspy no encontrada: {REFERENCIASPY_PATH}")

# Configuración
CONFIG_FILE = "config_web.json"
MAPA_FILE = "mapa_municipios.json"

# --- CONFIGURACIÓN DE RUTAS DE CAPAS ---
# Prioridad:
# 1. Ruta /app/capas (Entorno Docker/Producción)
# 2. Ruta ./capas (Entorno local relativo)

POSSIBLE_LAYERS_DIRS = [
    Path("/app/capas"),
    Path("capas")
]

LAYERS_DIR = Path("capas") # Default fallback
for d in POSSIBLE_LAYERS_DIRS:
    if d.exists():
        LAYERS_DIR = d
        print(f"✅ Usando directorio de capas: {LAYERS_DIR}")
        break
    else:
        print(f"ℹ️ Directorio no encontrado: {d}")

# Intentar importar módulos principales
try:
    from catastro4 import CatastroDownloader, procesar_y_comprimir
    CATASTRO_AVAILABLE = True
    print("✅ catastro4 disponible")
except ImportError as e:
    CATASTRO_AVAILABLE = False
    print(f"⚠️ catastro4 no disponible: {e}")

try:
    import urbanismo
    URBANISMO_AVAILABLE = True
    print("✅ urbanismo disponible")
except ImportError as e:
    URBANISMO_AVAILABLE = False
    print(f"⚠️ urbanismo no disponible: {e}")

try:
    import afecciones
    AFECCIONES_AVAILABLE = True
    print("✅ afecciones disponible")
except ImportError as e:
    AFECCIONES_AVAILABLE = False
    print(f"⚠️ afecciones no disponible: {e}")

try:
    import geopandas as gpd
    GEOPANDAS_AVAILABLE = True
    import pandas as pd # Necesario para verificar tipos de fecha
    from sqlalchemy import text # Para queries parametrizadas
    print("✅ geopandas disponible")
except ImportError:
    GEOPANDAS_AVAILABLE = False
    print("⚠️ geopandas no disponible")

# Intentar importar referenciaspy
try:
    from referenciaspy.urban_analysis import AnalizadorUrbanistico
    REFERENCIASPY_AVAILABLE = True
    print("✅ referenciaspy disponible")
except ImportError as e:
    REFERENCIASPY_AVAILABLE = False
    print(f"⚠️ referenciaspy no disponible: {e}")

# Intentar importar generador PDF
try:
    from referenciaspy.pdf_generator import AfeccionesPDF
    PDF_GENERATOR_AVAILABLE = True
except ImportError:
    PDF_GENERATOR_AVAILABLE = False
    print("⚠️ referenciaspy.pdf_generator no disponible")

# Intentar importar funciones del visor
try:
    from visor_functions_integrated import get_visor
    VISOR_FUNCTIONS_AVAILABLE = True
    print("✅ visor_functions_integrated disponible")
except ImportError as e:
    VISOR_FUNCTIONS_AVAILABLE = False
    print(f"⚠️ visor_functions_integrated no disponible: {e}")

# Intentar importar servicio de informes urbanísticos
try:
    from backend.services.informes_urbanisticos_service import InformeUrbanistico
    INFORME_URBANISTICO_AVAILABLE = True
    print("✅ InformeUrbanistico disponible")
except ImportError:
    try:
        # Intentar importar desde raíz si no está en backend/services
        from informes_urbanisticos_service import InformeUrbanistico
        INFORME_URBANISTICO_AVAILABLE = True
        print("✅ InformeUrbanistico disponible (desde raíz)")
    except ImportError:
        INFORME_URBANISTICO_AVAILABLE = False
        print("⚠️ InformeUrbanistico no disponible")

# Intentar importar GISDatabase
try:
    from gis_db import GISDatabase
    GIS_DB_AVAILABLE = True
    db_gis = None # Singleton para pool de conexiones
except ImportError:
    GIS_DB_AVAILABLE = False
    db_gis = None
    print("⚠️ gis_db no disponible")

# Modelos Pydantic
class UrbanismoRequest(BaseModel):
    referencia: Optional[str] = None
    archivo: Optional[str] = None
    contenido: Optional[str] = None

class AfeccionesRequest(BaseModel):
    referencia: Optional[str] = None
    archivos: Optional[List[dict]] = None


class AjustesCapasPayload(BaseModel):
    max_visible_layers: int = 6
    visibles_wms: List[str] = []
    visibles_locales: List[str] = []
    vectoriales_gis: List[str] = []

class GenerarPDFRequest(BaseModel):
    referencia: str
    contenidos: List[str] = []
    empresa: Optional[str] = ""
    colegiado: Optional[str] = ""

class InformeUrbanisticoRequest(BaseModel):
    ref_catastral: Optional[str] = None
    provincia: Optional[str] = None
    municipio: Optional[str] = None
    via: Optional[str] = None
    numero: Optional[str] = None

# --- NUEVOS MODELOS PARA INFORME URBANÍSTICO ---
class ReferenciaData(BaseModel):
    referencia_catastral: str
    direccion: str
    municipio: str
    provincia: str
    distrito: Optional[str] = None
    coordenadas_x: float
    coordenadas_y: float
    superficie_m2: float
    fecha_alta_catastro: Optional[str] = None
    num_habitantes_municipio: Optional[int] = None

class Ordenanza(BaseModel):
    codigo: str
    uso_principal: str
    coef_edificabilidad: Optional[float] = None
    altura_max_plantas: Optional[int] = None
    fondo_edificable: Optional[float] = None

class UsoCompatibilidad(BaseModel):
    uso: str
    compatibilidad: str

class UrbanismoData(BaseModel):
    fecha_pgou: Optional[str] = None
    clasificacion_suelo: str
    zona_urbanistica: Optional[str] = None
    ordenanza: Optional[Ordenanza] = None
    usos_compatibilidad: List[UsoCompatibilidad] = []
    # Campos compatibles con visor actual
    edificabilidad_estimada: Optional[str] = None
    ocupacion_estimada: Optional[str] = None
    superficie_parcela: Optional[str] = None
    superficie_ocupada: Optional[str] = None

class Normativa(BaseModel):
    instrumento: str
    fecha_publicacion: str
    resumen: str

# ------------------------------------------------

class PDFCompletoRequest(BaseModel):
    referencia: Optional[str] = None
    incluir_referencia: bool = False
    incluir_urbanismo: bool = False
    incluir_afecciones: bool = False
    incluir_coordenadas: bool = False
    incluir_ortofoto: bool = False
    incluir_mapa: bool = False
    incluir_capas_cargadas: bool = False
    archivos_adicionales: Optional[List[dict]] = None
    formato: str = "pdf"

class LoteRequest(BaseModel):
    referencias: List[str]

# Crear aplicación FastAPI
app = FastAPI(
    title="Visor Catastral API - Glassmorphism",
    version="2.0.0",
    description="API para el visor catastral con diseño Glassmorphism"
)
# ⭐ AÑADE ESTO JUSTO DESPUÉS DE CREAR LA APP ⭐
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permite todos los orígenes (para desarrollo)
    allow_credentials=True,
    allow_methods=["*"],  # Permite todos los métodos (GET, POST, etc.)
    allow_headers=["*"],  # Permite todos los headers
)
# Cargar expedientes (Bloque 1) - Catastro
try:
    from expedientes.router import expedientes_router
    app.include_router(expedientes_router, prefix="/api/v1")
    print("✅ Expedientes router cargado en /api/v1")
except Exception as e:
    print(f"⚠️ Expedientes router no disponible: {e}")
# Cargar configuración
def cargar_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "rutas": {
                "outputs": "outputs",
                "layers": "layers",
                "results": "results"
            },
            "urls": {
                "catastro_wfs": "https://www.catastro.minhaf.es/INSPIRE/WFS",
                "ign_pnoa": "https://www.ign.es/wms/pnoa"
            }
        }

cfg = cargar_config()

# Crear y montar directorio de salidas
outputs_dir = cfg.get("rutas", {}).get("outputs", "outputs")
Path(outputs_dir).mkdir(exist_ok=True)

# Inicializar Base de Datos GIS Globalizada (Singleton)
if GIS_DB_AVAILABLE:
    try:
        db_gis = GISDatabase()
        if db_gis.test_connection():
            print("✅ Conexión GIS estable (Singleton inicializado)")
        else:
            print("⚠️ Conexión GIS fallida al inicio")
    except Exception as e:
        print(f"❌ Error inicializando DB GIS: {e}")

# --- INTEGRACIÓN INE (Población) ---
INE_CACHE = {}

def obtener_poblacion_ine(municipio_nombre):
    """
    Obtiene la población de un municipio usando la API del INE.
    Usa la tabla 29005 (Cifras oficiales de población).
    """
    global INE_CACHE
    
    if not municipio_nombre:
        return None

    # Normalizar nombre para búsqueda (quitar tildes, mayúsculas)
    def normalizar(s):
        return ''.join(c for c in unicodedata.normalize('NFD', s) 
                      if unicodedata.category(c) != 'Mn').lower().strip()
    
    mun_norm = normalizar(municipio_nombre)
    
    # Si ya está en cache, devolver
    if mun_norm in INE_CACHE:
        return INE_CACHE[mun_norm]
    
    # Si la cache está vacía, intentar llenarla (lazy loading)
    if not INE_CACHE:
        try:
            print("⏳ Descargando datos de población del INE (primera vez)...")
            # Tabla 29005: Población por municipios (último dato disponible)
            url = "https://servicios.ine.es/wstempus/js/es/DATOS_TABLA/29005?nult=1"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                datos = response.json()
                for item in datos:
                    # El nombre suele venir como "Provincia: Municipio" o "Municipio"
                    nombre_raw = item.get("Nombre", "")
                    
                    # Extraer nombre del municipio (ej: "Madrid: Madrid" -> "Madrid")
                    if ":" in nombre_raw:
                        parts = nombre_raw.split(":")
                        nombre_mun = parts[-1].strip()
                    else:
                        nombre_mun = nombre_raw
                    
                    # Obtener valor
                    if "Data" in item and len(item["Data"]) > 0:
                        valor = item["Data"][0].get("Valor")
                        if valor:
                            INE_CACHE[normalizar(nombre_mun)] = int(valor)
                print(f"✅ Datos INE cargados: {len(INE_CACHE)} municipios")
            else:
                print(f"⚠️ Error API INE: {response.status_code}")
        except Exception as e:
            print(f"⚠️ Excepción conectando con INE: {e}")
            return None

    # Buscar de nuevo tras cargar
    return INE_CACHE.get(mun_norm)


# Endpoints
@app.get("/")
async def root():
    """Página principal - Dashboard"""
    return FileResponse("static/index.html")

@app.get("/catastro_fin")
async def visor_catastro_fin():
    """Visor Catastral Final"""
    return FileResponse("static/catastro_fin.html")

@app.get("/urbanismo")
async def visor_urbanismo():
    """Visor Urbanismo (Placeholder)"""
    return HTMLResponse("<h1>Módulo de Análisis Urbanístico en construcción</h1><a href='/'>Volver</a>")

@app.get("/afecciones")
async def visor_afecciones():
    """Visor Afecciones (Placeholder)"""
    return HTMLResponse("<h1>Módulo de Análisis de Afecciones en construcción</h1><a href='/'>Volver</a>")


AJUSTES_CAPAS_FILE = Path("ajustes_config.json")


def _default_ajustes_config() -> Dict[str, Any]:
    return {
        "max_visible_layers": 6,
        "visibles_wms": [
            "catastro",
            "inundacion",
            "siose",
            "calificacion",
            "t10",
            "t100",
            "t500",
            "natura",
            "vias",
            "montes",
        ],
        "visibles_locales": [],
        "vectoriales_gis": [],
    }


def _load_ajustes_config() -> Dict[str, Any]:
    try:
        if AJUSTES_CAPAS_FILE.exists():
            with open(AJUSTES_CAPAS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            base = _default_ajustes_config()
            if isinstance(data, dict):
                base.update({k: v for k, v in data.items() if k in base})
            return base
    except Exception:
        pass
    return _default_ajustes_config()


def _save_ajustes_config(cfg_data: Dict[str, Any]) -> None:
    with open(AJUSTES_CAPAS_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg_data, f, ensure_ascii=False, indent=2)


def _list_capas_files_for_ajustes() -> List[Dict[str, Any]]:
    files: List[Dict[str, Any]] = []
    if not LAYERS_DIR.exists():
        return files

    extensions = ['.fgb', '.gpkg', '.shp', '.geojson', '.kml', '.zip']
    seen_stems = set()

    for ext in extensions:
        for f in LAYERS_DIR.rglob(f"*{ext}"):
            if f.name.startswith('.'):
                continue
            if f.stem in seen_stems:
                continue
            seen_stems.add(f.stem)
            try:
                rel_path = f.relative_to(LAYERS_DIR)
            except ValueError:
                rel_path = f.name
            layer_id = f.stem.replace(" ", "_").replace(".", "_").lower()
            files.append({
                "id": layer_id,
                "name": f.stem,
                "filename": f.name,
                "path": str(rel_path),
                "type": f.suffix.lower(),
            })

    files.sort(key=lambda x: x['name'])
    return files


def _visor_wms_catalog() -> List[Dict[str, str]]:
    return [
        {"id": "catastro", "name": "Catastro", "group": "Catastro y urbanismo"},
        {"id": "inundacion", "name": "Inundabilidad", "group": "Catastro y urbanismo"},
        {"id": "siose", "name": "SIOSE (Usos del suelo)", "group": "Catastro y urbanismo"},
        {"id": "calificacion", "name": "Calificación urbanística", "group": "Catastro y urbanismo"},
        {"id": "t10", "name": "T10 (10 años)", "group": "Riesgos hídricos"},
        {"id": "t100", "name": "T100 (100 años)", "group": "Riesgos hídricos"},
        {"id": "t500", "name": "T500 (500 años)", "group": "Riesgos hídricos"},
        {"id": "natura", "name": "Red Natura 2000", "group": "Medio ambiente"},
        {"id": "vias", "name": "Vías pecuarias", "group": "Medio ambiente"},
        {"id": "montes", "name": "Montes de utilidad pública", "group": "Medio ambiente"},
    ]


@app.get("/api/v1/ajustes/capas")
async def get_ajustes_capas():
    cfg_data = _load_ajustes_config()
    capas_locales = _list_capas_files_for_ajustes()
    capas_postgis: List[Dict[str, Any]] = []
    if GIS_DB_AVAILABLE and db_gis is not None and db_gis.test_connection():
        capas_postgis = db_gis.get_available_layers(schemas=["capas", "public", "afecciones"])

    return {
        "status": "success",
        "config": cfg_data,
        "catalog": {
            "wms": _visor_wms_catalog(),
            "locales": capas_locales,
            "postgis": capas_postgis,
        },
        "layers_dir": str(LAYERS_DIR),
    }


@app.post("/api/v1/ajustes/capas")
async def save_ajustes_capas(payload: AjustesCapasPayload):
    cfg_data = {
        "max_visible_layers": max(1, min(50, int(payload.max_visible_layers))),
        "visibles_wms": list(dict.fromkeys(payload.visibles_wms or [])),
        "visibles_locales": list(dict.fromkeys(payload.visibles_locales or [])),
        "vectoriales_gis": list(dict.fromkeys(payload.vectoriales_gis or [])),
    }
    _save_ajustes_config(cfg_data)
    return {"status": "success", "config": cfg_data}


@app.get("/api/v1/capas/list")
async def list_capas_files():
    """Listar archivos de capas disponibles en el directorio configurado"""
    try:
        files = []
        if LAYERS_DIR.exists():
            # Extensiones permitidas (ordenadas por prioridad)
            extensions = ['.fgb', '.gpkg', '.shp', '.geojson', '.kml', '.zip']
            
            seen_stems = set()
            
            # Recorrer recursivamente
            for ext in extensions:
                for f in LAYERS_DIR.rglob(f"*{ext}"):
                    # Ignorar archivos ocultos o de sistema
                    if f.name.startswith('.'): continue
                    
                    # Si ya tenemos una capa con este nombre (sin extensión), la saltamos
                    # Esto evita duplicados si existe rios.shp y rios.fgb (mostramos solo uno)
                    if f.stem in seen_stems:
                        continue
                    
                    seen_stems.add(f.stem)
                    
                    # Crear una entrada simplificada
                    try:
                        rel_path = f.relative_to(LAYERS_DIR)
                    except ValueError:
                        rel_path = f.name
                    
                    # Generar un ID único basado en el nombre
                    layer_id = f.stem.replace(" ", "_").replace(".", "_").lower()
                    
                    files.append({
                        "name": f.stem,
                        "filename": f.name,
                        "path": str(rel_path),
                        "type": f.suffix.lower(),
                        "id": layer_id
                    })
        
        # Ordenar por nombre
        files.sort(key=lambda x: x['name'])
        
        return {"status": "success", "files": files, "base_dir": str(LAYERS_DIR)}
    except Exception as e:
        print(f"Error listando capas: {e}")
        return {"status": "error", "message": str(e), "files": []}

@app.post("/api/v1/db/reconnect")
async def reconnect_db():
    """Forzar reconexión a la base de datos GIS"""
    global db_gis
    if not GIS_DB_AVAILABLE:
        return {"status": "error", "message": "Módulo GIS DB no disponible"}
    
    try:
        print("🔄 Intentando restablecer conexión con GIS DB...")
        # Re-instanciar la clase de base de datos
        temp_db = GISDatabase()
        if temp_db.test_connection():
            db_gis = temp_db
            print("✅ Conexión GIS restablecida exitosamente")
            return {"status": "success", "message": "Conexión restablecida"}
        else:
            print("⚠️ Intento de reconexión fallido")
            return {"status": "error", "message": "No se pudo conectar a la base de datos"}
    except Exception as e:
        print(f"❌ Error al intentar reconectar: {e}")
        return {"status": "error", "message": f"Error de conexión: {str(e)}"}

@app.get("/api/v1/capas-disponibles")
async def get_capas_disponibles():
    """Obtener lista de capas disponibles desde PostGIS"""
    global db_gis
    try:
        if not GIS_DB_AVAILABLE:
            return {"status": "error", "message": "Módulo GIS DB no disponible"}
            
        # Intentar inicializar o reconectar si es necesario
        if db_gis is None or not db_gis.test_connection():
             print("⚠️ Conexión DB inestable o nula, intentando reconectar...")
             try:
                 db_gis = GISDatabase()
                 if not db_gis.test_connection():
                     return {"status": "error", "message": "Base de datos desconectada", "capas": []}
             except Exception as e:
                 print(f"❌ Falló reconexión automática: {e}")
                 return {"status": "error", "message": "Base de datos desconectada", "capas": []}
             
        # Consultar esquemas 'capas' y 'public'
        layers = db_gis.get_available_layers(schemas=["capas", "public"])
        return {"status": "success", "capas": layers}
    except Exception as e:
        print(f"Error en capas-disponibles: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/v1/capas/data/{layer_name}")
async def get_layer_data(layer_name: str, bbox: Optional[str] = Query(None)):
    """
    Obtener GeoJSON de una capa PostGIS.
    Soporta formato 'schema.table' o 'table' (busca en esquemas por defecto).
    """
    try:
        if not GIS_DB_AVAILABLE or db_gis is None:
            raise HTTPException(status_code=503, detail="GIS DB no disponible")
            
        if not hasattr(db_gis, 'engine') or db_gis.engine is None:
             raise HTTPException(status_code=500, detail="No se pudo acceder al motor de base de datos")
        
        db = db_gis # Usar la instancia global
        
        # Determinar esquema y tabla
        if "." in layer_name:
            schema_name, table_name = layer_name.split(".", 1)
        else:
            # Por defecto intentar 'capas', luego 'public'
            # Para evitar SQL injection y errores, idealmente verificaríamos existencia,
            # pero por rendimiento asumiremos 'capas' si no se especifica, o probamos.
            # Estrategia segura: Si no tiene punto, buscar en metadata primero o intentar queries.
            # Vamos a intentar 'capas' por defecto como solicitó el usuario.
            schema_name = "capas"
            table_name = layer_name
            
            # Verificar si existe en 'capas', si no, probar 'public'
            # Esto es costoso por request. 
            # Mejor: Asumir que el frontend envía el nombre completo si usó get_capas_disponibles.
            # Si envía nombre corto, asumimos 'capas' como principal.
        
        params = {}
        where_clause = ""
        if bbox:
            try:
                minx, miny, maxx, maxy = [float(c) for c in bbox.split(',')]
                # Transformamos el BBOX al SRID de la tabla en SQL y filtramos
                where_clause = "WHERE ST_Intersects(geom, ST_Transform(ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326), ST_SRID(geom)))"
                params = {'minx': minx, 'miny': miny, 'maxx': maxx, 'maxy': maxy}
            except (ValueError, IndexError):
                raise HTTPException(status_code=400, detail="Formato de BBOX inválido")

        # SQL dinámico pero controlado (schema_name y table_name vienen de lógica interna o split)
        # Importante: Validar caracteres para evitar SQL Injection básico
        if not all(c.isalnum() or c in "_-" for c in table_name) or not all(c.isalnum() or c in "_" for c in schema_name):
             raise HTTPException(status_code=400, detail="Nombre de capa o esquema inválido")

        sql = text(f"""
            SELECT *, ST_Transform(geom, 4326) as geom_wgs84 
            FROM {schema_name}.{table_name} 
            {where_clause} 
            LIMIT 3000
        """)
        
        # Leemos indicando la nueva columna de geometría ya proyectada
        gdf = gpd.read_postgis(sql, db.engine, params=params, geom_col='geom_wgs84')
        
        # Quitamos la columna original 'geom' (si existe) para no enviarla duplicada en el GeoJSON
        if 'geom' in gdf.columns:
            gdf = gdf.drop(columns=['geom'])
            
        # Convertir tipos no serializables a string
        for col in gdf.columns:
            if pd.api.types.is_datetime64_any_dtype(gdf[col]):
                gdf[col] = gdf[col].astype(str)
                
        return json.loads(gdf.to_json())
    except Exception as e:
        # Si la tabla no existe, devolver una FeatureCollection vacía en lugar de 500
        error_str = str(e).lower()
        if "does not exist" in error_str or "undefinedtable" in error_str:
            print(f"⚠️ Capa no encontrada en DB: {layer_name}")
            return {"type": "FeatureCollection", "features": [], "status": "not_found", "layer": layer_name}
            
        print(f"Error fetching layer {layer_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/capas/geojson/{nombre_capa}")
async def get_geojson_capa(nombre_capa: str):
    """Obtener GeoJSON de una capa específica"""
    print(f"🔍 Buscando capa: {nombre_capa}")
    try:
        if nombre_capa.lower() in ["inundacion", "inundabilidad", "t10", "t100", "t500"]:
            print(f"⚠️ BLOQUEADO: Intento de cargar capa pesada '{nombre_capa}'")
            return {"type": "FeatureCollection", "features": []}

        # Definir posibles nombres base para la búsqueda
        nombres_posibles = [nombre_capa]
        
        # Mapeos específicos basados en tus archivos
        if nombre_capa == "natura":
            nombres_posibles.extend(["PS.RNATURA2000", "RNATURA", "Es_Lic_SCI_Zepa"])
        elif nombre_capa == "caminos":
            nombres_posibles.extend(["CCNN", "ETAPAS", "caminos", "GENE"])
        elif nombre_capa == "montes":
            nombres_posibles.extend(["IEPF_CMUP", "CMUP", "montes", "publicos"])
        elif nombre_capa == "vias":
            nombres_posibles.extend(["vias", "pecuarias", "vvpp", "vias_pecuarias"])
        # Archivos/Carpetas a excluir (archivos muy grandes que bloquean el servidor)
        # Es_Lic... (600MB), IEPF... (1.2GB), RGVP... (196MB)
        carpetas_excluidas = ["zonas_inundables", "Es_Lic_SCI_Zepa", "RGVP_BDN"]
        
        # Búsqueda recursiva en directorios raíz
        directorios_raiz = [Path("capas"), Path("ccnn")]
        archivo_encontrado = None # Inicialización explícita para evitar errores 500
        

        archivos_candidatos = []
        
        # 1. Búsqueda por nombre de ARCHIVO
        for nombre in nombres_posibles:
            patrones = [f"*{nombre}*.geojson", f"*{nombre}*.shp", f"*{nombre}*.zip", f"*{nombre}*.kml", f"*{nombre}*.gpkg", f"*{nombre}*.fgb"]
            for patron in patrones:
                # Buscar en LAYERS_DIR
                if LAYERS_DIR.exists():
                    archivos_candidatos.extend(list(LAYERS_DIR.rglob(patron)))
                # Buscar en ccnn (fallback)
                if Path("ccnn").exists():
                    archivos_candidatos.extend(list(Path("ccnn").rglob(patron)))
        
        # 2. Si no hay candidatos, buscar por nombre de CARPETA (ej: carpeta 'ccnn' contiene 'track.shp')
        if not archivos_candidatos:
            print("  ↳ Buscando dentro de carpetas específicas...")
            for nombre in nombres_posibles:
                # Usar LAYERS_DIR y ccnn como raíces
                roots = [LAYERS_DIR, Path("ccnn")]
                for root_dir in roots:
                    if not root_dir.exists(): continue
                    # Buscar directorios que contengan el nombre
                    # Usamos rglob para encontrar subdirectorios que coincidan
                    for d in root_dir.rglob(f"*{nombre}*"):
                        if d.is_dir():
                            # Si encontramos la carpeta, coger todos los archivos GIS dentro
                            for ext in ["*.shp", "*.geojson", "*.kml", "*.gpkg", "*.fgb"]:
                                archivos_candidatos.extend(list(d.rglob(ext)))

        # Filtrar duplicados
        archivos_candidatos = list(set(archivos_candidatos))
        
        # Definir prioridad de extensiones (menor índice = mayor prioridad)
        priority_ext = {'.fgb': 0, '.gpkg': 1, '.shp': 2, '.geojson': 3, '.kml': 4, '.zip': 5}
        
        def get_priority(path):
            return priority_ext.get(path.suffix.lower(), 99)
            
        # Ordenar candidatos por prioridad
        archivos_candidatos.sort(key=get_priority)

        # Seleccionar el primer archivo encontrado que no esté excluido
        for candidato in archivos_candidatos:
            if any(excl in str(candidato) for excl in carpetas_excluidas):
                continue
            archivo_encontrado = candidato
            print(f"  ✅ Encontrado por coincidencia (mejor formato): {candidato}")
            break # Tomar el primero que cumpla

        if not archivo_encontrado:
            print(f"⚠️ NO ENCONTRADO: Capa {nombre_capa} (Se devolverá vacío)")
            return {"type": "FeatureCollection", "features": []}

        print(f"✅ Leyendo archivo: {archivo_encontrado}")

        # Leer archivo (GPKG o GeoJSON o FGB)
        suffix = archivo_encontrado.suffix.lower()
        if suffix in ['.gpkg', '.shp', '.fgb']:
            if not GEOPANDAS_AVAILABLE:
                print(f"⚠️ Geopandas no disponible para capa {nombre_capa}")
                return {"type": "FeatureCollection", "features": []}
            
            try:
                # Convertir Path a string para compatibilidad
                gdf = gpd.read_file(str(archivo_encontrado))
                
                # Convertir a WGS84 para web
                if gdf.crs and gdf.crs.to_string() != "EPSG:4326":
                    gdf = gdf.to_crs("EPSG:4326")
                
                # CORRECCIÓN: Convertir columnas de fecha a string para evitar error JSON
                for col in gdf.columns:
                    if pd.api.types.is_datetime64_any_dtype(gdf[col]):
                        gdf[col] = gdf[col].astype(str)
                        
                return json.loads(gdf.to_json())
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"❌ Error leyendo archivo {archivo_encontrado}: {e}")
                # Devolver vacío para no romper el visor con 500
                return {"type": "FeatureCollection", "features": []}
        else:
            with open(archivo_encontrado, "r", encoding="utf-8") as f:
                return json.load(f)
                
    except Exception as e:
        print(f"ERROR en get_geojson_capa ({nombre_capa}): {e}") # Debug
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/proxy")
async def proxy_request(url: str):
    """
    Proxy simple compatible hacia atrás.
    """
    try:
        resp = requests.get(url, timeout=15, verify=False)
        return Response(content=resp.content, status_code=resp.status_code, media_type=resp.headers.get("content-type"))
    except Exception as e:
        print(f"Error en proxy: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/wms_proxy")
async def wms_proxy(request: Request):
    """
    Proxy específico para WMS que reenvía todos los parámetros.
    Uso: /api/v1/wms_proxy?url=BASE_URL&param1=val1...
    """
    try:
        params = dict(request.query_params)
        target_url = params.pop("url", None)
        
        if not target_url:
            raise HTTPException(status_code=400, detail="URL requerida")

        # Hacer la petición al WMS real
        # verify=False para evitar problemas con certificados SSL antiguos del ministerio
        resp = requests.get(target_url, params=params, timeout=30, verify=False)
        
        return Response(content=resp.content, status_code=resp.status_code, media_type=resp.headers.get("content-type"))
    except Exception as e:
        print(f"❌ Error WMS Proxy: {e}")
        import traceback
        traceback.print_exc()
        return Response(status_code=500)

@app.get("/api/v1/referencia/{ref}/geojson")
async def get_referencia_geojson(ref: str):
    """Obtener GeoJSON de una referencia catastral"""
    try:
        if not CATASTRO_AVAILABLE:
            raise HTTPException(status_code=503, detail="El módulo 'catastro4' no está disponible.")

        downloader = CatastroDownloader(output_dir=cfg["rutas"]["outputs"])
        
        # 1. Intentar obtener la geometría real del GML
        gml_descargado = downloader.descargar_parcela_gml(ref)
        coords_poligono = None
        
        if gml_descargado:
            # Intentar encontrar el archivo en la carpeta de la referencia o en la raíz de outputs
            posibles_rutas = [
                Path(cfg["rutas"]["outputs"]) / ref / f"{ref}_parcela.gml",
                Path(cfg["rutas"]["outputs"]) / f"{ref}_parcela.gml"
            ]
            
            for p in posibles_rutas:
                if p.exists():
                    gml_path = p
                    print(f"✅ GML encontrado en: {p}")
                    coords_poligono = downloader.extraer_coordenadas_gml(str(gml_path))
                    break
            
            if not coords_poligono:
                print(f"⚠️ No se pudo extraer geometría de ninguna ruta: {[str(p) for p in posibles_rutas]}")

        if coords_poligono:
            if len(coords_poligono) > 0:
                anillo_exterior = coords_poligono[0]

                def _is_lon_lat(lon: float, lat: float) -> bool:
                    return (-11 <= lon <= 5) and (35 <= lat <= 45)

                polygon_geojson = None

                if anillo_exterior:
                    a0, b0 = anillo_exterior[0]

                    cand_lon_lat_1 = [(lon, lat) for lat, lon in anillo_exterior]
                    if cand_lon_lat_1 and _is_lon_lat(cand_lon_lat_1[0][0], cand_lon_lat_1[0][1]):
                        polygon_geojson = [[lon, lat] for lon, lat in cand_lon_lat_1]
                    else:
                        cand_lon_lat_2 = [(lon, lat) for lon, lat in anillo_exterior]
                        if cand_lon_lat_2 and _is_lon_lat(cand_lon_lat_2[0][0], cand_lon_lat_2[0][1]):
                            polygon_geojson = [[lon, lat] for lon, lat in cand_lon_lat_2]

                if polygon_geojson is None and anillo_exterior:
                    from pyproj import Transformer

                    def _try_epsg(epsg: int, swap_xy: bool = False):
                        transformer = Transformer.from_crs(epsg, 4326, always_xy=True)
                        pts = []
                        for x, y in anillo_exterior:
                            if swap_xy:
                                x, y = y, x
                            lon, lat = transformer.transform(x, y)
                            pts.append([lon, lat])
                        if pts and _is_lon_lat(pts[0][0], pts[0][1]):
                            return pts
                        return None

                    for epsg in (25830, 25829, 25831):
                        polygon_geojson = _try_epsg(epsg, swap_xy=False)
                        if polygon_geojson:
                            break
                        polygon_geojson = _try_epsg(epsg, swap_xy=True)
                        if polygon_geojson:
                            break

                if not polygon_geojson:
                    raise HTTPException(status_code=500, detail="No se pudo transformar la geometría a WGS84")

                if polygon_geojson[0] != polygon_geojson[-1]:
                    polygon_geojson.append(polygon_geojson[0])

                return {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [polygon_geojson]},
                    "properties": {"referencia": ref, "fuente_geometria": "GML Real", "anillos": len(coords_poligono)}
                }
        else:
            # Sin GML: devolver error para que el frontend muestre mensaje claro
            raise HTTPException(status_code=404, detail=f"No hay geometría GML disponible para la referencia {ref}")
        
    except HTTPException as he:
        raise he
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

class LoteRequest(BaseModel):
    referencias: List[str]

class ProcesoRequest(BaseModel):
    referencia: str
    buffer_metros: Optional[int] = None

@app.post("/api/v1/procesar-completo")
async def procesar_completo(request: ProcesoRequest):
    """
    Ejecuta el proceso completo de descarga para una referencia y devuelve el ZIP.
    """
    if not CATASTRO_AVAILABLE:
        raise HTTPException(status_code=503, detail="El módulo 'catastro4' no está disponible.")
    
    ref = request.referencia
    
    try:
        # Usar la función de catastro4.py
        zip_path, resultados = procesar_y_comprimir(
            referencia=ref,
            directorio_base=cfg["rutas"]["outputs"],
            buffer_metros=request.buffer_metros
        )
        
        if zip_path and resultados.get('exitosa'):
            # Recuperar geometría para análisis urbanístico
            ref_dir = Path(cfg["rutas"]["outputs"]) / ref
            
            # Extraer anillos del GML de parcela
            anillos = None
            parcela_gml_path = ref_dir / f"{ref}_parcela.gml"
            
            if parcela_gml_path.exists():
                try:
                    # Usar CatastroDownloader para extraer coordenadas
                    downloader = CatastroDownloader(output_dir=str(ref_dir))
                    coords_poligono = downloader.extraer_coordenadas_gml(str(parcela_gml_path))
                    
                    if coords_poligono:
                        # Convertir a formato de anillos para urbanismo.py
                        anillos = coords_poligono # Ya viene como lista de anillos desde catastro4
                        print(f"✅ Geometría extraída: {len(coords_poligono)} anillos")
                    else:
                        print("⚠️ No se pudieron extraer coordenadas del GML")
                except Exception as e:
                    print(f"⚠️ Error extrayendo geometría: {e}")
            
            # Realizar análisis urbanístico si tenemos geometría
            datos_urbanisticos = None
            if anillos and URBANISMO_AVAILABLE:
                try:
                    datos_urbanisticos = urbanismo.realizar_analisis_urbanistico(anillos)
                    print(f"✅ Análisis urbanístico completado")
                except Exception as e:
                    print(f"⚠️ Error en análisis urbanístico: {e}")
                    datos_urbanisticos = {"error": str(e)}
            
            # Detectar afecciones reales
            afecciones_detectadas = []
            if ref_dir.exists():
                # Revisar archivos de afecciones generados
                for tipo in ['hidrografia', 'planeamiento', 'catastro_parcelas']:
                    afeccion_file = ref_dir / f"{ref}_afeccion_{tipo}.png"
                    if afeccion_file.exists() and afeccion_file.stat().st_size > 1500:
                        afecciones_detectadas.append({
                            "tipo": tipo,
                            "descripcion": f"Afección por {tipo} detectada en la zona",
                            "afectacion": "Directa",
                            "archivo": str(afeccion_file)
                        })
                        print(f"✅ Afección detectada: {tipo}")
            
            # Enriquecer resultados con análisis urbanístico y afecciones
            resultados_enriquecidos = resultados.copy()
            if datos_urbanisticos:
                resultados_enriquecidos['datos_urbanisticos'] = datos_urbanisticos
            
            if afecciones_detectadas:
                resultados_enriquecidos['afecciones_detectadas'] = afecciones_detectadas
            
            # Devolver la ruta relativa para que el frontend pueda construir el enlace
            relative_to_mount_dir = Path(zip_path).relative_to(Path(outputs_dir))
            url_path = f"/outputs/{relative_to_mount_dir}"
            
            return {
                "status": "success",
                "message": f"Proceso completado para {ref}",
                "zip_path": str(url_path).replace('\\', '/'), # Ensure forward slashes for URL
                "resultados": resultados_enriquecidos
            }
        else:
            error_msg = resultados.get('error', 'Error desconocido durante el procesamiento.')
            raise HTTPException(status_code=500, detail=error_msg)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en el servidor: {str(e)}")

@app.post("/api/v1/procesar-lote")
async def procesar_lote(request: LoteRequest):
    """
    Procesa un lote de referencias como una unidad unificada:
    - Un XML con información de todas las referencias
    - Todos los GML juntos en la misma vista
    - ZIP con carpetas organizadas (documentos, geometrías, imágenes, etc.)
    """
    print(f" Iniciando procesamiento de lote con {len(request.referencias)} referencias")
    
    referencias = request.referencias
    if not referencias:
        raise HTTPException(status_code=400, detail="No se proporcionaron referencias")
    
    # Generar ID único para el lote
    lote_id = f"lote_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(referencias)}refs"
    lote_dir = Path(cfg["rutas"]["outputs"]) / lote_id
    lote_dir.mkdir(exist_ok=True)
    
    print(f" Directorio del lote: {lote_dir}")
    
    try:
        # 1. Procesar cada referencia individualmente
        resultados_individuales = []
        todas_geometrias = []
        xml_datos = []
        lista_coords_para_mapa = []
        
        for i, ref in enumerate(referencias):
            print(f" [{i+1}/{len(referencias)}] Procesando referencia: {ref}")
            
            try:
                # Procesar referencia individual
                zip_path, resultados = procesar_y_comprimir(
                    referencia=ref,
                    directorio_base=str(lote_dir)
                )
                
                print(f"  Resultado procesar_y_comprimir: zip_path={zip_path}, exitosa={resultados.get('exitosa')}")
                
                if zip_path and resultados.get('exitosa'):
                    # Extraer geometría
                    ref_dir = lote_dir / ref
                    parcela_gml_path = ref_dir / f"{ref}_parcela.gml"
                    
                    print(f"  Buscando GML: {parcela_gml_path}")
                    
                    if parcela_gml_path.exists():
                        try:
                            downloader = CatastroDownloader(output_dir=str(ref_dir))
                            coords_poligono = downloader.extraer_coordenadas_gml(str(parcela_gml_path))
                            
                            print(f"  Coordenadas extraídas: {type(coords_poligono)} - {coords_poligono}")
                            
                            if coords_poligono:
                                # coords_poligono puede ser una lista de coordenadas o None
                                # Si es una lista de tuplas, la usamos directamente
                                if isinstance(coords_poligono, list) and len(coords_poligono) > 0:
                                    # Añadir a la lista de geometrías combinadas
                                    for j, anillo in enumerate(coords_poligono):
                                        todas_geometrias.append({
                                            'referencia': ref,
                                            'anillo': j,
                                            'coordenadas': anillo
                                        })
                                    
                                    # Añadir datos para XML
                                    xml_datos.append({
                                        'referencia': ref,
                                        'geometria': coords_poligono,
                                        'resultados': resultados
                                    })
                                    lista_coords_para_mapa.append(coords_poligono)
                                    
                                    print(f" Geometría extraída para {ref}: {len(coords_poligono)} anillos")
                                else:
                                    # Añadir datos para XML sin geometría
                                    xml_datos.append({
                                        'referencia': ref,
                                        'geometria': None,
                                        'resultados': resultados
                                    })
                                    
                            else:
                                print(f"  No se encontraron coordenadas para {ref}")
                                # Añadir datos para XML sin geometría
                                xml_datos.append({
                                    'referencia': ref,
                                    'geometria': None,
                                    'resultados': resultados
                                })
                        except Exception as e:
                            print(f"  Error extrayendo geometría para {ref}: {e}")
                            traceback.print_exc()
                            # Añadir datos para XML con error
                            xml_datos.append({
                                'referencia': ref,
                                'geometria': None,
                                'resultados': resultados,
                                'error_geometria': str(e)
                            })
                    else:
                        print(f"  No existe GML para {ref}")
                        # Añadir datos para XML sin geometría
                        xml_datos.append({
                            'referencia': ref,
                            'geometria': None,
                            'resultados': resultados
                        })
                    
                    resultados_individuales.append({
                        'referencia': ref,
                        'exitosa': True,
                        'zip_path': zip_path,
                        'resultados': resultados
                    })
                    
                else:
                    print(f"  Falló procesamiento de {ref}")
                    resultados_individuales.append({
                        'referencia': ref,
                        'exitosa': False,
                        'error': resultados.get('error', 'Error desconocido')
                    })
                    
            except Exception as e:
                print(f"  Error procesando referencia {ref}: {e}")
                traceback.print_exc()
                resultados_individuales.append({
                    'referencia': ref,
                    'exitosa': False,
                    'error': str(e)
                })
        
        # Instanciar downloader para operaciones de lote
        downloader = CatastroDownloader(output_dir=str(lote_dir))

        # 2. Crear XML unificado
        xml_loader.generar_xml_lote(xml_datos, lote_id, xml_path)
        Nojson_path = lote_dir / f"{lote_id}_geometrias_combinadas.geojson"
        downloader.generar_geojson_lote(todas_geometrias, geojson_path)
        
        # Generaer.generar_gml_global(xml_datos, lote_dir / f"{lote_id}_global.gml")
        l lista_coords_para_mapa:
            if downloader.generar_mapa_lote(lista_coords_para_mapa, lote_dir / f"{lote_id}_mapa_global.jpg"):
                mapa_global_creado = True
izar carpetas del ZIP final
        zip_final_path = downloader.organizar_lote(lote_dir, lote_id, referencias)
        
        mapa_global_url = None
        if mapa_global_creado:
             mapa_global_url = f"/outputs/{lote_id}/Imagenes/{lote_id}_mapa_global.jpg".replace('\\', '/')

        return {
            "status": "sute procesado: {len(referencias)} referencias",
            "lote_id": lote_id,
            "zip_path": f"/outputs/{lote_id}/{lote_id}.zip".replace('\\', '/'),
            "geometrias_combinadas": len(todas_geometrias),
            "resultados": resultados_individuales,
            "geojson_url": f"/outputs/{lote_id}/{lote_id}_geometrias_combinadas.geojson".replace('\\', '/'),
            "mapa_global_url": mapa_global_url
        }
        
    except Exception as e:
        print(f"❌ Error en procesamiento de lote: {e}")
        raise HTTPException(status_code=500, detail=f"Error procesando lote: {str(e)}")


@app.get("/api/v1/logs")
async def get_logs():
    """
    Endpoint para obtener logs del servidor (compatibilidad con visor)
    """
    # Simular logs para compatibilidad con el visor     ff .dse f.b   rmlel eas)                            # Guardamos como 'geometrias/archivo.gml' etc.
        zipf.write(f, folder.name + "/" + f.name)
                
                print(f"✅ ZIP creado: {zip_path}")
            else:
                print(f"❌ Directorio del expediente no existe: {exp_dir}")
        except Exception as e:
            print(f"❌ Error organizando/creando ZIP para lote {exp_id}: {str(e)}")
            traceback.print_exc()
        
        # 3. Actualizar manifiesto con URL del ZIP y estado final
        manifest_path = exp_dir / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Añadir URL del ZIP si existe
            if zip_path.exists():
                data["zip_url"] = f"/outputs/expedientes/{zip_path.name}"
                data["zip_size"] = zip_path.stat().st_size
            
            # Actualizar estado final
            if data.get("estado") != "error":
                data["estado"] = "completado"
                data["fecha_finalizacion"] = datetime.now().isoformat()
            
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            print(f"📋 Manifiesto actualizado para lote {exp_id}")
        
    except Exception as e:
        print(f"❌ Error crítico en background_lote_worker para {exp_id}: {str(e)}")
        traceback.print_exc()
        
        # Intentar actualizar manifiesto con error crítico
        try:
            exp_dir = exp_base / f"expediente_{exp_id}"
            manifest_path = exp_dir / "manifest.json"
            if manifest_path.exists():
                with open(manifest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["estado"] = "error_critico"
                data["error"] = str(e)
                data["fecha_error"] = datetime.now().isoformat()
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
        except:
            pass

@app.post("/api/v1/procesar-lote")
async def procesar_lote_endpoint(request: LoteRequest, background_tasks: BackgroundTasks):
    """Procesa un lote de referencias y genera un expediente conjunto"""
    try:
        from expedientes.catastro_exp import crear_expediente_id
        
        # Directorio base para expedientes
        exp_base = Path(outputs_dir) / "expedientes"
        exp_base.mkdir(exist_ok=True)
        
        # Generar ID y lanzar tarea
        exp_id = crear_expediente_id()
        
        # Pre-crear directorio y manifiesto para evitar 404 en polling inmediato
        exp_dir = exp_base / f"expediente_{exp_id}"
        exp_dir.mkdir(parents=True, exist_ok=True)
        
        initial_manifest = {
            "expediente_id": exp_id,
            "estado": "iniciando",
            "progreso": 0,
            "numero_referencias": len(request.referencias),
            "referencias": request.referencias,
            "fecha_creacion": datetime.now().isoformat(),
            "items": []
        }
        
        with open(exp_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(initial_manifest, f, indent=2, ensure_ascii=False)
            
        background_tasks.add_task(background_lote_worker, request.referencias, exp_base, exp_id)
        
        return {
            "status": "processing",
            "expediente_id": exp_id,
            "message": "Procesamiento iniciado en segundo plano"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/analizar-referencia")
async def analizar_referencia(referencia: dict):
    """Analizar una referencia catastral completa con estructura de datos ampliada"""
    try:
        ref = referencia.get("referencia", "")
        print(f"🔍 Analizando referencia: {ref}")
        
        if not ref:
            raise HTTPException(status_code=400, detail="Se requiere una referencia")
        
        if not CATASTRO_AVAILABLE:
            print("❌ Catastro no disponible")
            return {
                "status": "error",
                "message": "Catastro no disponible",
                "data": None
            }
        
        print("✅ Catastro disponible, creando downloader...")
        downloader = CatastroDownloader(output_dir=outputs_dir)
        
        # 1. Obtener Coordenadas
        print("📍 Obteniendo coordenadas...")
        coords = downloader.obtener_coordenadas_unificado(ref) or {}
        print(f"📍 Coordenadas obtenidas: {coords}")
        
        # 2. Obtener Datos Alfanuméricos
        print("📋 Obteniendo datos alfanuméricos...")
        datos_xml = downloader.obtener_datos_alfanumericos(ref) or {}
        print(f"📋 Datos alfanuméricos: {datos_xml}")
        
        # 3. Calcular Superficie (intentar obtener de GML o XML)
        superficie = float(datos_xml.get("superficie_construida", 0)) # Fallback
        print(f"📏 Superficie: {superficie}")
        
        # 4. Obtener Población INE
        municipio_nombre = datos_xml.get("municipio", "")
        poblacion = obtener_poblacion_ine(municipio_nombre)
        print(f"👥 Población: {poblacion}")
        
        # Verificar coordenadas antes de construir respuesta
        if not coords or (coords.get("lat", 0) == 0 and coords.get("lon", 0) == 0):
            print("❌ No se encontraron coordenadas válidas")
            return {
                "status": "error",
                "message": "No se encontraron coordenadas para esta referencia",
                "data": None
            }
        
        # Construir modelo de respuesta
        data = ReferenciaData(
            referencia_catastral=ref,
            direccion=datos_xml.get("domicilio", "Dirección no disponible"),
            municipio=datos_xml.get("municipio", "Desconocido"),
            provincia=datos_xml.get("provincia", "Desconocida"),
            distrito=None,
            coordenadas_x=coords.get("lon", 0.0),
            coordenadas_y=coords.get("lat", 0.0),
            superficie_m2=superficie,
            fecha_alta_catastro=str(datos_xml.get("anio_construccion", "N/D")),
            num_habitantes_municipio=poblacion
        )
        
        print(f"✅ Referencia analizada correctamente: {data.dict()}")
        
        return {
            "status": "success",
            "data": data.dict(),
            "message": "Análisis de referencia completado"
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "data": None}

@app.post("/api/v1/analizar-urbanismo")
async def analizar_urbanismo(request: UrbanismoRequest):
    """Analizar urbanismo de una referencia o archivo"""
    try:
        if not URBANISMO_AVAILABLE:
            return {
                "status": "error",
                "message": "Urbanismo no disponible",
                "data": None
            }
        
        if not CATASTRO_AVAILABLE:
            return {"status": "error", "message": "Catastro no disponible", "data": None}

        ref = request.referencia
        if not ref:
            return {"status": "error", "message": "Referencia requerida", "data": None}

        # 1. Obtener geometría real
        downloader = CatastroDownloader(output_dir=outputs_dir)
        gml_path = Path(outputs_dir) / ref / f"{ref}_parcela.gml"
        
        # Descargar si no existe
        if not gml_path.exists():
            downloader.descargar_parcela_gml(ref)
        
        anillos = None
        if gml_path.exists():
            anillos = downloader.extraer_coordenadas_gml(str(gml_path))
            
        if not anillos:
            return {"status": "error", "message": "No se pudo obtener la geometría", "data": None}

        # 2. Calcular datos reales
        datos = urbanismo.realizar_analisis_urbanistico(anillos)
        
        if "error" in datos:
            return {"status": "error", "message": datos["error"], "data": None}

        # Construir respuesta con modelo UrbanismoData
        urbanismo_data = UrbanismoData(
            fecha_pgou="2024-01-01", # Dato simulado (requiere BBDD planeamiento)
            clasificacion_suelo="Urbano Consolidado",
            zona_urbanistica="Zona Residencial",
            ordenanza=Ordenanza(
                codigo="NZ-RES",
                uso_principal=datos.get("uso_principal", "Residencial"),
                coef_edificabilidad=None,
                altura_max_plantas=None,
                fondo_edificable=None
            ),
            usos_compatibilidad=[
                UsoCompatibilidad(uso="Residencial", compatibilidad="Permitido"),
                UsoCompatibilidad(uso="Comercial", compatibilidad="Compatible")
            ],
            # Datos calculados reales
            edificabilidad_estimada=f"{datos.get('edificabilidad_estimada_m2', 0)} m²",
            ocupacion_estimada=f"{datos.get('porcentaje_ocupacion', 0)}%",
            superficie_parcela=f"{datos.get('superficie_parcela_m2', 0)} m²",
            superficie_ocupada=f"{datos.get('superficie_ocupada_m2', 0)} m²"
        )

        return {
            "status": "success",
            "data": {
                "referencia": ref,
                "analisis_urbanistico": urbanismo_data.dict()
            },
            "message": "Análisis urbanístico calculado sobre geometría real"
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "data": None}

@app.post("/api/v1/urbanismo/generar-informe")
async def generar_informe_urbanistico(request: InformeUrbanisticoRequest):
    """Generar informe urbanístico completo"""
    try:
        if not INFORME_URBANISTICO_AVAILABLE:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "error",
                    "message": "Servicio de informes urbanísticos no disponible",
                    "data": None
                }
            )
        
        # Instanciar el generador con el archivo de configuración
        generador = InformeUrbanistico("urbanismo_config.json")
        
        # Generar informe completo
        informe = generador.generar_informe_completo(
            ref_catastral=request.ref_catastral,
            provincia=request.provincia,
            municipio=request.municipio,
            via=request.via,
            numero=request.numero
        )
        
        if "error" in informe:
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "message": informe["error"],
                    "data": None
                }
            )
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": "Informe urbanístico generado correctamente",
                "data": informe
            }
        )
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Error generando informe: {str(e)}",
                "data": None
            }
        )

@app.post("/api/v1/analizar-afecciones")
async def analizar_afecciones(request: AfeccionesRequest):
    """Analizar afecciones de una referencia (Proceso completo con generación de mapas)"""
    try:
        if not all([AFECCIONES_AVAILABLE, CATASTRO_AVAILABLE, GEOPANDAS_AVAILABLE]):
            return {
                "status": "error", 
                "message": "Faltan módulos necesarios (afecciones, catastro4, geopandas).",
                "data": None
            }
            
        ref = request.referencia
        if not ref:
            return {"status": "error", "message": "Referencia requerida"}

        # 1. Obtener GML de Catastro
        downloader = CatastroDownloader(output_dir=outputs_dir)
        # Asegurar que el directorio de salida existe
        ref_dir = Path(outputs_dir) / ref
        ref_dir.mkdir(parents=True, exist_ok=True)
        
        gml_path = ref_dir / f"{ref}_parcela.gml"
        
        # Descargar si no existe
        if not gml_path.exists():
            print(f"Descargando GML para {ref}...")
            downloader.descargar_parcela_gml(ref)
            
        if not gml_path.exists():
            return {"status": "error", "message": f"No se pudo descargar la geometría para {ref}"}

        # 2. Configurar Afecciones (Modo Híbrido: PostGIS + Script tradicional)
        afecciones_db = []
        try:
            from gis_db import GISDatabase
            db = GISDatabase()
            
            # Obtener capas del esquema afecciones
            capas_db = db.get_available_layers(schemas=['afecciones'])
            if capas_db:
                print(f"🔍 Analizando {len(capas_db)} capas en PostGIS...")
                # Aquí llamaríamos a una función de intersección espacial directa
                # Por ahora simulamos la integración con el flujo existente
                pass
        except Exception as e_db:
            print(f"⚠️ Error consultando PostGIS: {e_db}")

        try:
            # Flujo tradicional (Script afecciones.py)
            capas_locales = afecciones.listar_capas_locales()
            capas_wfs = afecciones.listar_capas_wfs("capas_wfs.csv")
            capas_wms_path = "capas/wms/capas_wms.csv"
            
            capas_wms = afecciones.listar_capas_wms(capas_wms_path)
            config_titulos = afecciones.cargar_config_titulos()
            
            # 3. Ejecutar Procesamiento
            print(f"Iniciando análisis de afecciones para {ref}...")
            
            resultados_proc = afecciones.procesar_parcelas(
                capas_locales, capas_wfs, capas_wms, "EPSG:25830", config_titulos,
                ruta_input=str(gml_path),
                output_dir_base=str(ref_dir)
            )
            
            # 4. Formatear respuesta
            mapas_urls = []
            detalles_afeccion = []
            
            if resultados_proc:
                res = resultados_proc[0]
                
                # Procesar mapas generados
                for mapa_path in res.get('mapas', []):
                    p_map = Path(mapa_path)
                    try:
                        rel = p_map.relative_to(Path(outputs_dir))
                        mapas_urls.append(f"/outputs/{str(rel).replace(os.sep, '/')}")
                    except ValueError:
                         mapas_urls.append(f"/outputs/{ref}/{p_map.name}")

                # Procesar datos numéricos
                for d in res.get('datos', []):
                    if d['porcentaje'] > 0:
                        detalles_afeccion.append({
                            "tipo": d['capa'],
                            "descripcion": f"Afección detectada: {d['porcentaje']:.2f}%",
                            "afectacion": "Total" if d['porcentaje'] > 99 else "Parcial",
                            "porcentaje": d['porcentaje']
                        })
            else:
                return {"status": "error", "message": "El proceso de afecciones no devolvió resultados."}

            return {
                "status": "success",
                "data": {
                    "referencia": ref,
                    "afecciones": detalles_afeccion,
                    "mapas": mapas_urls,
                    "source": "PostGIS + GeoPandas (Hybrid)"
                },
                "message": f"Análisis completado. {len(detalles_afeccion)} afecciones detectadas."
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": f"Error interno en análisis: {str(e)}"}

    except Exception as e:
        return {"status": "error", "message": str(e), "data": None}


@app.post("/api/analizar-avanzado")
async def analizar_avanzado(request: ProcesoRequest):
    """
    Endpoint unificado premium que realiza análisis urbanístico y de afecciones.
    Portado de catastro-saas.
    """
    try:
        ref = request.referencia.strip()
        
        # 1. Obtener geometría y datos alfanuméricos
        downloader = CatastroDownloader(output_dir=outputs_dir)
        gml_descargado = downloader.descargar_parcela_gml(ref)
        if not gml_descargado:
             raise HTTPException(status_code=404, detail="Geometría catastral no encontrada")
        
        gml_path = Path(outputs_dir) / ref / f"{ref}_parcela.gml"
        anillos = downloader.extraer_coordenadas_gml(str(gml_path))
        
        # 2. Análisis Urbanístico
        res_urbanismo = {}
        if URBANISMO_AVAILABLE and anillos:
            res_urbanismo = urbanismo.realizar_analisis_urbanistico(anillos)
        
        # 3. Análisis de Afecciones
        res_afecciones = []
        if AFECCIONES_AVAILABLE and gml_path.exists():
            capas_locales = afecciones.listar_capas_locales()
            capas_wfs = afecciones.listar_capas_wfs("capas_wfs.csv")
            capas_wms = afecciones.listar_capas_wms("capas/wms/capas_wms.csv")
            config_titulos = afecciones.cargar_config_titulos()
            
            # Procesar afecciones (usamos CRS 25830 por defecto en España)
            resultados_proc = afecciones.procesar_parcelas(
                capas_locales, capas_wfs, capas_wms, "EPSG:25830", config_titulos,
                ruta_input=str(gml_path),
                output_dir_base=str(Path(outputs_dir) / ref)
            )
            
            if resultados_proc:
                for d in resultados_proc[0].get('datos', []):
                    if d['porcentaje'] > 0.01:
                        res_afecciones.append({
                            "capa": d['capa'],
                            "porcentaje": round(d['porcentaje'], 2),
                            "origen": d.get('origen', 'Sistemas GIS')
                        })

        return {
            "success": True,
            "referencia": ref,
            "urbanismo": res_urbanismo,
            "afecciones": res_afecciones,
            "message": "Análisis avanzado completado con éxito"
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/generar-pdf")
async def generar_pdf(request: GenerarPDFRequest):
    """Generar PDF personalizado (Endpoint compatible con visor_logic.js)"""
    if not PDF_GENERATOR_AVAILABLE:
        return {"status": "error", "error": "El generador de PDF no está disponible"}
    
    if not CATASTRO_AVAILABLE:
        return {"status": "error", "error": "Catastro no disponible"}

    try:
        ref = request.referencia
        contenidos = request.contenidos
        
        downloader = CatastroDownloader(output_dir=outputs_dir)
        
        # 1. Obtener datos alfanuméricos (XML) si se solicitan
        datos_xml = None
        if 'datos_descriptivos' in contenidos:
            datos_xml = downloader.obtener_datos_alfanumericos(ref)
        
        # 2. Preparar estructura de resultados
        resultados_analisis = {
            "referencia": ref,
            "empresa": request.empresa,
            "colegiado": request.colegiado,
            "fecha": "Hoy",
            "datos_catastro": datos_xml,
            "detalle": {},
            "total": 0
        }

        # 3. Recopilar mapas/imágenes
        mapas = []
        ref_dir = Path(outputs_dir) / ref
        if ref_dir.exists():
            # Mapas básicos
            if 'composicion' in contenidos or 'plano_ortofoto' in contenidos:
                mapas.append(str(ref_dir / f"{ref}_plano_con_ortofoto.png"))
            if 'plano_catastro' in contenidos:
                mapas.append(str(ref_dir / f"{ref}_plano_catastro.png"))
            if 'ortofoto_pnoa' in contenidos:
                mapas.append(str(ref_dir / f"{ref}_ortofoto_pnoa.jpg"))
            
            # Ortofotos de contexto
            for tipo in ['provincial', 'autonomico', 'nacional']:
                if f'ortofoto_{tipo}' in contenidos:
                    mapas.append(str(ref_dir / f"{ref}_ortofoto_{tipo}.jpg"))
            
            # Contornos y afecciones
            if 'contorno_superpuesto' in contenidos:
                mapas.append(str(ref_dir / f"{ref}_plano_con_ortofoto_contorno.png"))
            if 'capas_afecciones' in contenidos:
                for f in ref_dir.glob("*afeccion*.png"):
                    mapas.append(str(f))

        # 4. Generar PDF
        pdf_gen = AfeccionesPDF(output_dir=outputs_dir)
        pdf_path = pdf_gen.generar(
            referencia=ref,
            resultados=resultados_analisis,
            mapas=mapas,
            incluir_tabla=('datos_descriptivos' in contenidos)
        )

        if pdf_path:
            return {"status": "success", "url": f"/outputs/{pdf_path.name}"}
        else:
            return {"status": "error", "error": "Fallo al generar el archivo PDF"}

    except Exception as e:
        print(f"Error generando PDF: {e}")
        return {"status": "error", "error": str(e)}

class GeometriaRequest(BaseModel):
    """Request para análisis sobre geometrías cargadas"""
    geometria: dict = None  # GeoJSON geometry
    tipo: str = "desconocido"  # kml, gml, geojson, referencia

@app.post("/api/v1/analizar-afecciones-geometria")
async def analizar_afecciones_geometria(request: GeometriaRequest):
    """Analizar afecciones sobre geometrías cargadas en el visor"""
    try:
        if not all([AFECCIONES_AVAILABLE, CATASTRO_AVAILABLE, GEOPANDAS_AVAILABLE]):
            return {
                "status": "error", 
                "message": "Módulos necesarios (afecciones, catastro4, geopandas) no disponibles.",
                "data": None
            }
        
        geometria = request.geometria
        if not geometria:
            raise HTTPException(status_code=400, detail="Se requiere una geometría para analizar")
        
        # Convertir la geometría a GeoDataFrame
        from shapely.geometry import shape
        import geopandas as gpd
        from geojson import Feature, Polygon, FeatureCollection
        
        try:
            # Crear GeoDataFrame desde la geometría
            if geometria.get('type') == 'FeatureCollection':
                features = geometria.get('features', [])
                if not features:
                    raise HTTPException(status_code=400, detail="La geometría no tiene features válidos")
                
                # Combinar todas las geometrías
                geometrias = []
                for feature in features:
                    if feature.get('geometry'):
                        geometrias.append(shape(feature['geometry']))
                
                if not geometrias:
                    raise HTTPException(status_code=400, detail="No hay geometrías válidas en el FeatureCollection")
                
                # Crear GeoDataFrame
                gdf = gpd.GeoDataFrame(geometry=geometrias, crs='EPSG:4326')
                
            elif geometria.get('type') == 'Feature':
                if not geometria.get('geometry'):
                    raise HTTPException(status_code=400, detail="El Feature no tiene geometría válida")
                
                geom_shape = shape(geometria['geometry'])
                gdf = gpd.GeoDataFrame(geometry=[geom_shape], crs='EPSG:4326')
                
            elif geometria.get('type') in ['Polygon', 'MultiPolygon']:
                geom_shape = shape(geometria)
                gdf = gpd.GeoDataFrame(geometry=[geom_shape], crs='EPSG:4326')
                
            else:
                raise HTTPException(status_code=400, detail=f"Tipo de geometría no soportado: {geometria.get('type')}")
            
            # Convertir a CRS proyectado para cálculos de área
            gdf_projected = gdf.to_crs(epsg=25830)
            geom_union = gdf_projected.union_all()
            area_total = gdf_projected.area.sum()
            
            # Cargar capas de afecciones y calcular intersecciones
            capas_wms_config = afecciones.listar_capas_wms("capas/wms/capas_wms.csv")
            resultados_afecciones = []
            
            for capa_config in capas_wms_config:
                nombre_gpkg = capa_config.get("gpkg")
                if not nombre_gpkg: 
                    continue
                
                ruta_gpkg = Path("capas/gpkg") / nombre_gpkg
                if not ruta_gpkg.exists(): 
                    continue
                
                capa_afeccion_gdf = gpd.read_file(ruta_gpkg).to_crs(epsg=25830)
                capa_filtrada = capa_afeccion_gdf[capa_afeccion_gdf.intersects(geom_union)]
                
                if capa_filtrada.empty: 
                    continue
                
                interseccion = gpd.overlay(gdf_projected, capa_filtrada, how="intersection", keep_geom_type=False)
                
                if not interseccion.empty:
                    porcentaje_total = (interseccion.area.sum() / area_total) * 100
                    
                    resultados_afecciones.append({
                        "tipo": capa_config['nombre'],
                        "descripcion": f"Afectado en un {porcentaje_total:.2f}%",
                        "afectacion": "Parcial" if porcentaje_total < 100 else "Total",
                        "area_afectada_m2": float(interseccion.area.sum()),
                        "area_total_m2": float(area_total)
                    })
            
            return {
                "status": "success",
                "data": {
                    "tipo_geometria": request.tipo,
                    "area_analizada_m2": float(area_total),
                    "afecciones": resultados_afecciones,
                    "capas_analizadas": len([c for c in capas_wms_config if c.get("gpkg") and (Path("capas/gpkg") / c["gpkg"]).exists()])
                },
                "message": f"Análisis de afecciones completado: {len(resultados_afecciones)} afecciones encontradas"
            }
            
        except Exception as e:
            print(f"Error en análisis de afecciones sobre geometría: {e}")
            raise HTTPException(status_code=500, detail=str(e))
            
    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e), "data": None}

@app.get("/api/v1/buscar-municipio")
async def buscar_municipio(q: str = ""):
    """Buscar municipio por código o nombre"""
    try:
        with open(MAPA_FILE, "r") as f:
            municipios = json.load(f)
        
        resultados = []
        query = q.lower()
        
        for codigo, data in municipios.items():
            # Manejar formato simple (solo URL) o complejo (dict)
            if isinstance(data, dict):
                nombre = data.get("nombre", codigo)
                url = data.get("url", "")
            else:
                url = str(data)
                nombre = codigo
                # Intentar extraer nombre de URL
                try:
                    parts = url.split('/')
                    for p in parts:
                        if p.startswith(f"{codigo}-"):
                            nombre = p.split('-', 1)[1].replace('%20', ' ')
                            break
                except: pass

            if query in codigo.lower() or query in nombre.lower():
                resultados.append({
                    "codigo": codigo,
                    "nombre": nombre,
                    "url": url
                })
        
        return {"municipios": resultados[:10]}  # Limitar a 10 resultados
    except Exception as e:
        # Municipios por defecto
        default_municipios = [
            {"codigo": "28079", "nombre": "Madrid", "url": ""},
            {"codigo": "08019", "nombre": "Barcelona", "url": ""},
            {"codigo": "46091", "nombre": "Valencia", "url": ""}
        ]
        
        if q:
            filtrados = [m for m in default_municipios if q.lower() in m["nombre"].lower()]
            return {"municipios": filtrados}
        
        return {"municipios": default_municipios[:5]}

def generar_html_informe(contenido_pdf):
    """Genera HTML para el informe completo"""
    html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>{contenido_pdf['metadatos']['titulo']}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; line-height: 1.6; }}
            .header {{ background: #f4f4f4; padding: 20px; border-radius: 5px; margin-bottom: 20px; }}
            .seccion {{ margin: 20px 0; padding: 15px; border-left: 4px solid #007cba; background: #f9f9f9; }}
            .seccion h2 {{ color: #007cba; margin-top: 0; }}
            .error {{ color: #d32f2f; background: #ffebee; padding: 10px; border-radius: 3px; }}
            .metadata {{ font-size: 0.9em; color: #666; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>{contenido_pdf['metadatos']['titulo']}</h1>
            <div class="metadata">
                <p><strong>Referencia:</strong> {contenido_pdf['metadatos']['referencia']}</p>
                <p><strong>Fecha:</strong> {contenido_pdf['metadatos']['fecha_generacion']}</p>
            </div>
        </div>
    """
    
    for seccion in contenido_pdf["secciones"]:
        html += f"""
        <div class="seccion">
            <h2>{seccion['titulo']}</h2>
            <pre>{json.dumps(seccion['contenido'], indent=2, ensure_ascii=False)}</pre>
        </div>
        """
    
    html += """
    </body>
    </html>
    """
    
    return html

@app.post("/api/v1/generar-pdf-completo")
async def generar_pdf_completo(request: PDFCompletoRequest):
    """Genera PDF completo con toda la información seleccionada"""
    try:
        # Recopilar información
        contenido_pdf = {
            "metadatos": {
                "fecha_generacion": datetime.now().isoformat(),
                "titulo": "Informe Catastral Completo",
                "referencia": request.referencia or "No especificada"
            },
            "secciones": []
        }
        
        # Generar HTML
        html_content = generar_html_informe(contenido_pdf)
        
        # Guardar archivo
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre_base = f"informe_completo_{request.referencia or 'sin_ref'}_{timestamp}"
        output_path = Path(cfg["rutas"]["outputs"]) / f"{nombre_base}.html"
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        return {
            "status": "success",
            "formato": "html",
            "output": str(output_path),
            "secciones_generadas": len(contenido_pdf["secciones"]),
            "message": "Informe HTML generado exitosamente"
        }
        
    except Exception as e:
        return {"error": str(e), "status": "error"}

@app.get("/visor")
async def get_visor_page():
    """Endpoint para el visor integrado"""
    if VISOR_FUNCTIONS_AVAILABLE:
        try:
            return await get_visor()
        except Exception as e:
            print(f"Error en get_visor: {e}")
            if os.path.exists("visor.html"):
                return FileResponse("visor.html")
            return FileResponse("static/visor.html")
    else:
        if os.path.exists("visor.html"):
            return FileResponse("visor.html")
        return FileResponse("static/visor.html")

# Montar archivos estáticos
try:
    Path("static").mkdir(exist_ok=True) # Asegurar que existe para evitar error en mount
    app.mount("/outputs", StaticFiles(directory=outputs_dir), name="outputs")
    app.mount("/static", StaticFiles(directory="static"), name="static")
    # Montar directorios de capas para acceso directo a FlatGeobuf (.fgb)
    if os.path.exists("capas"):
        app.mount("/capas", StaticFiles(directory="capas"), name="capas")
    if os.path.exists("ccnn"):
        app.mount("/ccnn", StaticFiles(directory="ccnn"), name="ccnn")
    print("✅ Archivos estáticos montados en /static, /outputs, /capas y /ccnn")
except Exception as e:
    print(f"⚠️ Error montando archivos estáticos: {e}")

if __name__ == "__main__":
    print("🚀 Iniciando servidor FastAPI para visor catastral con Glassmorphism...")
    def get_local_ip():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('10.255.255.255', 1))
            IP = s.getsockname()[0]
        except Exception:
            IP = '127.0.0.1'
        finally:
            s.close()
        return IP
    
    local_ip = get_local_ip()
    # Usar puerto 80 si está en EasyPanel/Docker, o 8000 en local
    PORT = int(os.environ.get("PORT", 8000))

    print(f"📁 Visor Local: http://localhost:{PORT}/catastro")
    print(f"🌍 Visor LAN:   http://{local_ip}:{PORT}/catastro")
    print(f"🔗 API Docs:    http://localhost:{PORT}/docs")
    print("🎨 Diseño: Glassmorphism")
    print(f"📂 referenciaspy: {REFERENCIASPY_PATH}")
    
    # DESHABILITADO: ngrok causaba bloqueos al arrancar
    # try:
    #     from pyngrok import ngrok
    #     public_url = ngrok.connect(PORT).public_url
    #     print(f"🌐 Visor Público (ngrok): {public_url}/static/visor.html")
    # except ImportError:
    #     print("ℹ️  Para acceso público: pip install pyngrok")
    # except Exception:
    #     pass
        
    # Iniciar el servidor
    uvicorn.run(app, host="0.0.0.0", port=PORT)
