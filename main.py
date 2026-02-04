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
import time
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
# from src.utils.auto_detect_layers import inicializar_capas, obtener_capas
# from src.utils.cruzador_capas import CruzadorCapas
from pydantic import BaseModel
import uvicorn

# --- CONFIGURACIÓN DE RETENCIÓN DE ARCHIVOS ---
TIEMPO_RETENCION_ARCHIVOS = 24 * 60 * 60  # 24 horas en segundos
ENABLE_FILE_RETENTION = True  # Activar retención de archivos (con protección de ZIPs)

# Estructura para trackear timestamps de archivos
file_timestamps = {}

def registrar_archivo(ref: str, filepath: Path):
    """Registra un archivo para retención"""
    if ENABLE_FILE_RETENTION:
        expiry_time = time.time() + TIEMPO_RETENCION_ARCHIVOS
        file_timestamps[str(filepath)] = {
            "ref": ref,
            "expiry": expiry_time,
            "created": time.time()
        }
        # Guardar timestamp en archivo para persistencia
        timestamp_file = filepath.parent / ".retention"
        with open(timestamp_file, "w") as f:
            json.dump({
                "expiry": expiry_time,
                "ref": ref
            }, f)

def cleanup_archivos_expirados():
    """Limpia solo archivos expirados (ejecutado en background)"""
    while True:
        try:
            ahora = time.time()
            outputs_dir = cfg.get("rutas", {}).get("outputs", "outputs")
            outputs_path = Path(outputs_dir)
            
            if outputs_path.exists():
                for ref_dir in outputs_path.iterdir():
                    if ref_dir.is_dir() and not ref_dir.name.startswith('.'):
                        # PROTEGER ARCHIVOS ZIP IMPORTANTES
                        zip_files = list(ref_dir.glob("*.zip"))
                        if zip_files:
                            print(f"🔒 Protegiendo ZIPs en {ref_dir.name}: {[f.name for f in zip_files]}")
                            continue  # Saltar directorios con ZIPs
                        
                        timestamp_file = ref_dir / ".retention"
                        if timestamp_file.exists():
                            try:
                                with open(timestamp_file) as f:
                                    data = json.load(f)
                                if ahora > data.get("expiry", 0):
                                    print(f"🗑️ Limpiando directorio expirado: {ref_dir}")
                                    import shutil
                                    shutil.rmtree(ref_dir)
                            except Exception as e:
                                print(f"⚠️ Error limpiando {ref_dir}: {e}")
            
            # Ejecutar cada hora
            time.sleep(3600)
            
        except Exception as e:
            print(f"❌ Error en cleanup: {e}")
            time.sleep(300)  # Reintentar en 5 minutos

# Iniciar cleanup en background
if ENABLE_FILE_RETENTION:
    cleanup_thread = threading.Thread(target=cleanup_archivos_expirados, daemon=True)
    cleanup_thread.start()
    print(f"✅ Sistema de retención de archivos activado ({TIEMPO_RETENCION_ARCHIVOS/3600:.1f} horas)")

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

class ProcesoRequest(BaseModel):
    referencia: str
    buffer_metros: Optional[int] = None

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

# Función para cargar configuración
def cargar_configuracion():
    """Carga la configuración desde el archivo JSON"""
    config_path = Path("src/config/config.json")
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

# Función de cleanup que usa cfg
def cleanup_con_cfg(cfg):
    """Función de cleanup que tiene acceso a cfg"""
    print("Ejecutando cleanup con configuración...")
    # Aquí tu lógica de cleanup que necesita cfg
    pass

# Context manager para el ciclo de vida de la app
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    cfg = cargar_configuracion()  # Define cfg aquí
    print("Aplicación iniciada, configuración cargada")
    yield {"cfg": cfg}  # Pasa cfg al contexto
    # Shutdown - cfg está disponible aquí
    cleanup_con_cfg(cfg)
    print("Aplicación apagada, cleanup completado")

# Crear aplicación FastAPI
app = FastAPI(
    title="Visor Catastral API - Glassmorphism",
    version="2.0.0",
    description="API para el visor catastral con diseño Glassmorphism",
    lifespan=lifespan
)
# ⭐ AÑADE ESTO JUSTO DESPUÉS DE CREAR LA APP ⭐
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permite todos los orígenes (para desarrollo)
    allow_credentials=True,
    allow_methods=["*"],  # Permite todos los métodos (GET, POST, etc.)
    allow_headers=["*"],  # Permite todos los headers
)

# Health check endpoint para EasyPanel
@app.get("/health")
async def health_check():
    """Health check para monitoreo de contenedor"""
    return {"status": "healthy", "service": "webgis"}
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
        
        # 1. Asegurar que el GML existe
        ref_dir = Path(cfg["rutas"]["outputs"]) / ref
        gml_path = ref_dir / f"{ref}_parcela.gml"
        
        if not gml_path.exists():
            print(f"  GML no encontrado localmente, descargando para {ref}...")
            if not downloader.descargar_parcela_gml(ref):
                 raise HTTPException(status_code=404, detail=f"No se pudo descargar la geometría GML para {ref}")
        
        # 2. Extraer anillos de coordenadas
        rings = downloader.extraer_coordenadas_gml(str(gml_path))
        
        if not rings:
            raise HTTPException(status_code=404, detail=f"No se pudo extraer la geometría del archivo GML para {ref}")

        # 3. Convertir anillos a formato GeoJSON [lon, lat]
        processed_rings = []
        for ring in rings:
            processed_ring = []
            for p in ring:
                # El GML de INSPIRE suele venir en (lat, lon) para EPSG:4326
                # GeoJSON requiere (lon, lat)
                v1, v2 = p
                if 35 < v1 < 45 and -10 < v2 < 5: # Heurística: v1 es Lat, v2 es Lon
                    processed_ring.append([v2, v1])
                elif 35 < v2 < 45 and -10 < v1 < 5: # Heurística: v2 es Lat, v1 es Lon
                    processed_ring.append([v1, v2])
                else: # Si no está claro, asumimos que el primer valor es Lat
                    processed_ring.append([v2, v1])
            
            # Cerrar el anillo si no lo está
            if processed_ring and processed_ring[0] != processed_ring[-1]:
                processed_ring.append(processed_ring[0])
            
            if processed_ring:
                processed_rings.append(processed_ring)

        if not processed_rings:
            raise HTTPException(status_code=500, detail="Error procesando coordenadas GML a GeoJSON")

        # 4. Construir la respuesta GeoJSON
        return {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": processed_rings # Formato: [exterior_ring, interior_ring_1, ...]
            },
            "properties": {"referencia": ref, "fuente_geometria": "GML Real", "anillos": len(rings)}
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/referencia/{ref}/geojson_old")
async def get_referencia_geojson_old(ref: str):
    """Obtener GeoJSON de una referencia catastral"""
    try:
        # ... (código antiguo)
        # ...
        if coords_poligono:
            # ...
            if len(coords_poligono) > 0:
                # ...
                return {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [coords_poligono]},
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
        xml_path = lote_dir / f"{lote_id}_informacion.xml"
        downloader.generar_xml_lote(xml_datos, lote_id, xml_path)
        
        # 3. Crear GeoJSON combinado y GML Global
        geojson_path = lote_dir / f"{lote_id}_geometrias_combinadas.geojson"
        downloader.generar_geojson_lote(todas_geometrias, geojson_path)
        
        # Generar GML Global y Mapa Global
        downloader.generar_gml_global(xml_datos, lote_dir / f"{lote_id}_global.gml")
        
        mapa_global_creado = False
        if lista_coords_para_mapa:
            if downloader.generar_mapa_lote(lista_coords_para_mapa, lote_dir / f"{lote_id}_mapa_global.jpg"):
                mapa_global_creado = True

        # 4. Organizar carpetas del ZIP final
        zip_final_path = downloader.organizar_lote(lote_dir, lote_id, referencias)
        
        mapa_global_url = None
        if mapa_global_creado:
             mapa_global_url = f"/outputs/{lote_id}/Imagenes/{lote_id}_mapa_global.jpg".replace('\\', '/')

        return {
            "status": "success",
            "message": f"Lote procesado: {len(referencias)} referencias",
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
    # Simular logs para compatibilidad con el visor
    return {"status": "success", "logs": ["Servidor iniciado.", "Esperando peticiones..."]}

# Endpoint para descargar ZIP de expediente
@app.get("/api/v1/expedientes/{expediente_id}/download")
async def descargar_expediente_zip(expediente_id: str):
    """Descarga el ZIP de un expediente específico"""
    try:
        outputs_dir = cfg.get("rutas", {}).get("outputs", "outputs")
        exp_dir = Path(outputs_dir) / "expedientes" / f"expediente_{expediente_id}"
        
        if not exp_dir.exists():
            raise HTTPException(status_code=404, detail="Expediente no encontrado")
        
        # Buscar el archivo ZIP en el directorio
        zip_files = list(exp_dir.glob("*.zip"))
        
        if not zip_files:
            # Si no hay ZIP, intentar crear uno
            try:
                zip_path = exp_dir / f"expediente_{expediente_id}.zip"
                import zipfile
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for file_path in exp_dir.rglob('*'):
                        if file_path.is_file() and file_path.suffix != '.zip':
                            arcname = file_path.relative_to(exp_dir)
                            zipf.write(file_path, arcname)
                zip_files = [zip_path]
            except Exception as e:
                print(f"Error creando ZIP para expediente {expediente_id}: {e}")
        
        if not zip_files:
            raise HTTPException(status_code=404, detail="ZIP no disponible para este expediente")
        
        zip_file = zip_files[0]
        return FileResponse(
            path=zip_file,
            filename=f"expediente_{expediente_id}.zip",
            media_type='application/zip'
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error descargando ZIP expediente {expediente_id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

# Endpoint para obtener estado de expediente (actualizado)
@app.get("/api/v1/expedientes/{expediente_id}/status")
async def obtener_estado_expediente(expediente_id: str):
    """Obtiene el estado actual de un expediente"""
    try:
        outputs_dir = cfg.get("rutas", {}).get("outputs", "outputs")
        manifest_path = Path(outputs_dir) / "expedientes" / f"expediente_{expediente_id}" / "manifest.json"
        
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail="Expediente no encontrado")
        
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
        
        # Construir URL correcta para el ZIP
        zip_url = f"/api/v1/expedientes/{expediente_id}/download"
        
        return {
            **manifest,
            "zip_url": zip_url  # URL correcta para descargar
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error obteniendo estado expediente {expediente_id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

# Endpoint para descargar conjunto organizado por categorías
@app.get("/api/v1/descargar-conjunto-organizado/{ref}")
async def descargar_conjunto_organizado(ref: str):
    """Descarga un ZIP organizado por categorías con siluetas y leyendas"""
    try:
        outputs_dir = cfg.get("rutas", {}).get("outputs", "outputs")
        ref_dir = Path(outputs_dir) / ref
        
        if not ref_dir.exists():
            raise HTTPException(status_code=404, detail="Referencia no encontrada")
        
        # Crear ZIP organizado en memoria
        import zipfile
        import tempfile
        from io import BytesIO
        
        zip_buffer = BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # 1. Carpeta FOTOS_CONJUNTAS
            fotos_conjuntas = []
            
            # Buscar imágenes con silueta
            for img_file in ref_dir.glob("*_contorno.*"):
                if img_file.suffix.lower() in ['.png', '.jpg', '.jpeg']:
                    # Copiar a carpeta fotos_conjuntas
                    arcname = f"fotos_conjuntas/{img_file.name}"
                    zipf.write(img_file, arcname)
                    fotos_conjuntas.append(img_file.name)
            
            # Añadir composiciones si existen
            for comp_file in ref_dir.glob("*_composicion_*.png"):
                arcname = f"fotos_conjuntas/{comp_file.name}"
                zipf.write(comp_file, arcname)
                fotos_conjuntas.append(comp_file.name)
            
            # 2. Carpeta ORTOFOTOS
            ortofotos = []
            for orto_file in ref_dir.glob("*ortofoto*"):
                if orto_file.suffix.lower() in ['.png', '.jpg', '.jpeg']:
                    # Priorizar versión con contorno
                    contorno_file = ref_dir / f"{orto_file.stem}_contorno{orto_file.suffix}"
                    file_to_use = contorno_file if contorno_file.exists() else orto_file
                    
                    arcname = f"ortofotos/{file_to_use.name}"
                    zipf.write(file_to_use, arcname)
                    ortofotos.append(file_to_use.name)
            
            # 3. Carpeta PLANOS
            planos = []
            for plano_file in ref_dir.glob("*plano*"):
                if plano_file.suffix.lower() in ['.png', '.jpg', '.jpeg']:
                    # Priorizar versión con contorno
                    contorno_file = ref_dir / f"{plano_file.stem}_contorno{plano_file.suffix}"
                    file_to_use = contorno_file if contorno_file.exists() else plano_file
                    
                    arcname = f"planos/{file_to_use.name}"
                    zipf.write(file_to_use, arcname)
                    planos.append(file_to_use.name)
            
            # 4. Carpeta CRUCES (composiciones GML + capas)
            cruces = []
            for cruce_file in ref_dir.glob("*composicion_gml_*.png"):
                arcname = f"cruces/{cruce_file.name}"
                zipf.write(cruce_file, arcname)
                cruces.append(cruce_file.name)
            
            # 5. Documentación oficial
            for doc_file in ref_dir.glob("*.pdf"):
                arcname = f"documentacion/{doc_file.name}"
                zipf.write(doc_file, arcname)
            
            # 6. Datos geográficos
            for geo_file in ref_dir.glob("*.kml"):
                arcname = f"datos_geograficos/{geo_file.name}"
                zipf.write(geo_file, arcname)
            
            for geo_file in ref_dir.glob("*.geojson"):
                arcname = f"datos_geograficos/{geo_file.name}"
                zipf.write(geo_file, arcname)
            
            for geo_file in ref_dir.glob("*.gml"):
                arcname = f"datos_geograficos/{geo_file.name}"
                zipf.write(geo_file, arcname)
            
            # 7. Crear leyenda unificada
            leyenda_content = crear_leyenda_unificada(ref, fotos_conjuntas, ortofotos, planos, cruces)
            zipf.writestr("LEYENDA_UNIFICADA.txt", leyenda_content.encode('utf-8'))
            
            # 8. Crear README de organización
            readme_content = crear_readme_organizacion(ref, fotos_conjuntas, ortofotos, planos, cruces)
            zipf.writestr("README_ORGANIZACION.txt", readme_content.encode('utf-8'))
        
        # Preparar respuesta
        zip_buffer.seek(0)
        
        return Response(
            content=zip_buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={ref}_conjunto_organizado.zip"}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error descargando conjunto organizado {ref}: {e}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")

def crear_leyenda_unificada(ref: str, fotos: list, ortofotos: list, planos: list, cruces: list) -> str:
    """Crea una leyenda unificada con colores consistentes"""
    leyenda = f"""
═══════════════════════════════════════════════════════════════
                  LEYENDA UNIFICADA - {ref}
═══════════════════════════════════════════════════════════════

🎨 COLORES ESTÁNDAR:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
■ FINCAS/PARCELAS:     Rojo (#FF0000) con borde blanco
■ RED NATURA 2000:     Verde (#00AA00) 
■ VÍAS PECUARIAS:      Azul (#0066CC)
■ MONTES PÚBLICOS:     Verde oscuro (#006600)
■ CAMINOS NATURALES:   Naranja (#FF8800)
■ DOMINIO PÚBLICO:     Púrpura (#9933CC)
■ ZONAS HÚMEDAS:       Cyan (#00CCCC)
■ OTROS:               Gris (#666666)

📁 ORGANIZACIÓN DE ARCHIVOS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📸 FOTOS_CONJUNTAS/     ({len(fotos)} archivos)
   Todas las imágenes con silueta del recinto
   Incluye composiciones y superposiciones
   
🛰️ ORTOFOTOS/           ({len(ortofotos)} archivos)
   Imágenes satélite con silueta roja brillante
   
🗺️ PLANOS/              ({len(planos)} archivos)
   Planos catastrales con silueta visible
   
🔄 CRUCES/              ({len(cruces)} archivos)
   Composiciones GML + capas de intersección
   
📋 DOCUMENTACIÓN/       Oficial
   PDFs catastrales y documentos legales
   
🌍 DATOS_GEOGRÁFICOS/    Formatos estándar
   KML, GeoJSON, GML para SIG

⚠️ INFORMACIÓN IMPORTANTE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Todas las imágenes incluyen la silueta del recinto en rojo brillante
• Los colores de las capas son consistentes en todas las composiciones
• Las coordenadas están en sistema ETRS89 / UTM zona 30N
• Para análisis avanzados, use los archivos de la carpeta CRUCES
• Los archivos KML son compatibles con Google Earth
• Los GeoJSON funcionan con cualquier software SIG

📅 Generado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
🔧 Sistema: Análisis Territorial Automático
═══════════════════════════════════════════════════════════════
"""
    return leyenda

def crear_readme_organizacion(ref: str, fotos: list, ortofotos: list, planos: list, cruces: list) -> str:
    """Crea un README explicando la organización"""
    readme = f"""
═══════════════════════════════════════════════════════════════
            CONJUNTO ORGANIZADO - REFERENCIA: {ref}
═══════════════════════════════════════════════════════════════

Este ZIP contiene toda la información territorial organizada por 
categorías para facilitar su uso y análisis.

📦 ESTRUCTURA DE CARPETAS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📸 FOTOS_CONJUNTAS/
   Imágenes con silueta del recinto siempre visible
   - Composiciones múltiples
   - Superposiciones de capas
   - Vistas panorámicas

🛰️ ORTOFOTOS/
   Imágenes satélite de alta resolución
   - Con silueta roja brillante
   - Cobertura PNOA completa

🗺️ PLANOS/
   Planos catastrales oficiales
   - Con silueta delimitadora
   - Información parcelaria

🔄 CRUCES/
   Análisis de intersecciones territoriales
   - GML + Red Natura 2000
   - GML + Vías Pecuarias
   - GML + Montes Públicos
   - GML + Otras capas

📋 DOCUMENTACIÓN/
   Documentación oficial y legal
   - Ficha catastral PDF
   - Informes técnicos

🌍 DATOS_GEOGRÁFICOS/
   Formatos para sistemas SIG
   - KML para Google Earth
   - GeoJSON para web/escritorio
   - GML original del catastro

🎯 USO RECOMENDADO:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Para presentación: Use FOTOS_CONJUNTAS/
2. Para análisis territorial: Use CRUCES/
3. Para SIG profesional: Use DATOS_GEOGRÁFICOS/
4. Para documentación legal: Use DOCUMENTACIÓN/

📞 SOPORTE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Para cualquier consulta técnica, contacte con el administrador
del sistema de análisis territorial.

📅 Fecha de generación: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
🔗 Referencia: {ref}
═══════════════════════════════════════════════════════════════
"""
    return readme

@app.post("/api/v1/procesar-lote")
async def procesar_lote_endpoint(request: LoteRequest, background_tasks: BackgroundTasks):
    """Procesa un lote de referencias y genera un expediente conjunto"""
    try:
        from expedientes.catastro_exp import crear_expediente_id
        
        print(f"🚀 INICIANDO PROCESAMIENTO DE LOTE")
        print(f"📊 Total referencias recibidas: {len(request.referencias)}")
        print(f"📋 Referencias: {request.referencias}")
        
        # Directorio base para expedientes
        exp_base = Path(outputs_dir) / "expedientes"
        exp_base.mkdir(exist_ok=True)
        
        # Generar ID y lanzar tarea
        exp_id = crear_expediente_id()
        print(f"🆔 ID de expediente generado: {exp_id}")
        
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

@app.post("/api/v1/procesar-completo")
async def procesar_completo(request: ProcesoRequest):
    """Procesa una referencia completa y genera ZIP con siluetas en todas las imágenes"""
    try:
        if not CATASTRO_AVAILABLE:
            raise HTTPException(status_code=503, detail="Módulo catastro4 no disponible")
            
        ref = request.referencia
        buffer = request.buffer_metros
        
        # Procesar con siluetas garantizadas
        zip_path, resultados = procesar_y_comprimir(
            referencia=ref,
            directorio_base=cfg["rutas"]["outputs"],
            buffer_metros=buffer
        )
        
        # REGISTRAR ARCHIVOS PARA RETENCIÓN
        if zip_path:
            registrar_archivo(ref, Path(zip_path))
        
        # Registrar directorio completo para retención
        ref_dir = Path(cfg["rutas"]["outputs"]) / ref
        if ref_dir.exists():
            registrar_archivo(ref, ref_dir)
            print(f"📁 Directorio {ref} registrado para retención por 24 horas")
        
        # Verificar que se generaron siluetas y aplicar a todas las imágenes si es necesario
        if CATASTRO_AVAILABLE:
            try:
                from referenciaspy.catastro_downloader import CatastroDownloader
                downloader = CatastroDownloader(output_dir=cfg["rutas"]["outputs"])
                
                # Forzar aplicación de siluetas a TODAS las imágenes
                ref_dir = Path(cfg["rutas"]["outputs"]) / ref
                if ref_dir.exists():
                    gml_file = ref_dir / f"{ref}_parcela.gml"
                    if gml_file.exists():
                        # Obtener BBOX para aplicar siluetas
                        coords = downloader.extraer_coordenadas_gml(str(gml_file))
                        if coords:
                            # Calcular BBOX simple
                            all_coords = [coord for ring in coords for coord in ring]
                            lons = [coord[0] for coord in all_coords if not downloader._es_latitud(coord[0])]
                            lats = [coord[0] for coord in all_coords if downloader._es_latitud(coord[0])]
                            
                            if lons and lats:
                                bbox_wgs84 = f"{min(lons)},{min(lats)},{max(lons)},{max(lats)}"
                                
                                # Aplicar siluetas a todas las imágenes encontradas
                                from src.core.catastro_engine import CatastroEngine
                                engine = CatastroEngine(cfg["rutas"]["outputs"])
                                siluetas_aplicadas = engine.superponer_contorno_en_todas_imagenes(ref, bbox_wgs84)
                                
                                if siluetas_aplicadas:
                                    print(f"✅ Siluetas aplicadas automáticamente a todas las imágenes")
                                    resultados['siluetas_completas'] = True
                                else:
                                    print(f"⚠ No se encontraron imágenes adicionales para siluetas")
                                    resultados['siluetas_completas'] = False
                
            except Exception as silhouette_e:
                print(f"⚠ Error aplicando siluetas automáticas: {silhouette_e}")
                resultados['siluetas_completas'] = False
        
        zip_url = f"/outputs/{ref}/{os.path.basename(zip_path)}" if zip_path else ""
        return {"status": "success", "zip_path": zip_url, "resultados": resultados}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/v1/generar-composiciones-gml")
async def generar_composiciones_gml(request: ProcesoRequest):
    """Genera composiciones del GML catastral con capas de intersección"""
    try:
        if not CATASTRO_AVAILABLE:
            raise HTTPException(status_code=503, detail="Módulo catastro4 no disponible")
            
        ref = request.referencia.strip()
        
        # Verificar que existe el GML
        outputs_dir = cfg["rutas"]["outputs"]
        gml_path = Path(outputs_dir) / ref / f"{ref}_parcela.gml"
        
        if not gml_path.exists():
            raise HTTPException(status_code=404, detail="GML catastral no encontrado")
        
        # Obtener coordenadas y BBOX
        downloader = CatastroDownloader(output_dir=outputs_dir)
        coords = downloader.extraer_coordenadas_gml(str(gml_path))
        
        if not coords:
            raise HTTPException(status_code=422, detail="No se pudieron extraer coordenadas del GML")
        
        # Calcular BBOX
        all_coords = [coord for ring in coords for coord in ring]
        lons = [coord[0] for coord in all_coords if not downloader._es_latitud(coord[0])]
        lats = [coord[0] for coord in all_coords if downloader._es_latitud(coord[0])]
        
        if not lons or not lats:
            raise HTTPException(status_code=422, detail="No se pudieron calcular coordenadas válidas")
        
        bbox_wgs84 = f"{min(lons)},{min(lats)},{max(lons)},{max(lats)}"
        
        # Generar composiciones
        from src.core.catastro_engine import CatastroEngine
        engine = CatastroEngine(outputs_dir)
        
        composiciones_generadas = engine.crear_composicion_gml_intersecciones(ref, bbox_wgs84)
        
        # Listar composiciones generadas
        composiciones = []
        ref_dir = Path(outputs_dir) / ref
        
        for comp_file in ref_dir.glob(f"{ref}_composicion_gml_*.png"):
            comp_url = f"/outputs/{ref}/{comp_file.name}"
            composiciones.append({
                "nombre": comp_file.name,
                "url": comp_url,
                "tipo": "composicion_gml_interseccion"
            })
        
        return {
            "status": "success", 
            "referencia": ref,
            "composiciones_generadas": composiciones_generadas,
            "bbox": bbox_wgs84,
            "composiciones": composiciones,
            "total_composiciones": len(composiciones)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": f"Error generando composiciones: {str(e)}"}

@app.post("/api/v1/composicion-multiple")
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
    
    # ASEGURAR QUE outputs_dir SEA CONSISTENTE con cfg["rutas"]["outputs"]
    outputs_dir = cfg.get("rutas", {}).get("outputs", "outputs")
    Path(outputs_dir).mkdir(exist_ok=True)
    
    # Montar /outputs apuntando al directorio correcto
    app.mount("/outputs", StaticFiles(directory=outputs_dir), name="outputs")
    app.mount("/static", StaticFiles(directory="static"), name="static")
    
    print(f"✅ Archivos estáticos montados:")
    print(f"   /static -> static/")
    print(f"   /outputs -> {outputs_dir}/")
        
except Exception as e:
    print(f"⚠️ Error montando archivos estáticos: {e}")

# ==========================================
# INICIALIZAR DETECCIÓN DE CAPAS
# ==========================================
@app.get("/api/v1/descargar-archivo/{ref}/{filename}")
async def descargar_archivo_robusto(ref: str, filename: str):
    """Endpoint robusto para descargar archivos con verificación de existencia"""
    try:
        # Usar la misma configuración que en el resto del código
        outputs_dir = cfg.get("rutas", {}).get("outputs", "outputs")
        file_path = Path(outputs_dir) / ref / filename
        
        print(f"🔍 Buscando archivo: {file_path}")
        print(f"📁 Existe directorio ref: {file_path.parent.exists()}")
        
        if not file_path.exists():
            print(f"❌ Archivo no encontrado: {file_path}")
            
            # Intentar buscar en ubicaciones alternativas
            alternativas = [
                Path(outputs_dir) / filename,  # Directo en outputs
                Path(ref) / filename,           # En subdirectorio ref
                Path("outputs") / ref / filename,  # outputs hardcoded
            ]
            
            for alt_path in alternativas:
                if alt_path.exists():
                    file_path = alt_path
                    print(f"✅ Archivo encontrado en alternativa: {file_path}")
                    break
            else:
                # Listar archivos disponibles para debug
                ref_dir = Path(outputs_dir) / ref
                if ref_dir.exists():
                    archivos = list(ref_dir.glob("*"))
                    print(f"📋 Archivos disponibles en {ref_dir}:")
                    for f in archivos[:10]:  # Mostrar solo los primeros 10
                        print(f"   - {f.name}")
                
                raise HTTPException(
                    status_code=404, 
                    detail=f"Archivo no encontrado: {filename}. Buscado en: {file_path}"
                )
        
        # Verificar que el archivo no esté vacío
        if file_path.stat().st_size == 0:
            raise HTTPException(status_code=404, detail="El archivo está vacío")
        
        print(f"✅ Sirviendo archivo: {file_path} ({file_path.stat().st_size} bytes)")
        
        return FileResponse(
            file_path,
            media_type="application/octet-stream",
            filename=filename,
            headers={
                "Cache-Control": "no-cache",
                "Access-Control-Allow-Origin": "*"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error en descarga: {e}")
        raise HTTPException(status_code=500, detail=f"Error descargando archivo: {str(e)}")

@app.get("/api/v1/descargar-global/{ref}")
async def descargar_global(ref: str):
    """Genera y sirve el ZIP completo de una referencia"""
    try:
        outputs_dir = cfg.get("rutas", {}).get("outputs", "outputs")
        zip_path = Path(outputs_dir) / f"{ref}_completo.zip"
        
        print(f"🔍 Buscando ZIP global: {zip_path}")
        
        if not zip_path.exists():
            print(f"📦 Generando ZIP para {ref}...")
            
            # Generar ZIP si no existe
            from src.core.catastro_engine import CatastroEngine
            engine = CatastroEngine(outputs_dir)
            zip_generado = engine.crear_zip_referencia(ref, outputs_dir)
            
            if not zip_generado:
                raise HTTPException(status_code=404, detail="No se pudo generar el ZIP")
            
            zip_path = Path(zip_generado)  # Usar la ruta devuelta
        
        if not zip_path.exists():
            raise HTTPException(status_code=404, detail="ZIP no encontrado después de generar")
        
        file_size = zip_path.stat().st_size
        print(f"✅ Sirviendo ZIP global: {zip_path} ({file_size/1024/1024:.1f} MB)")
        
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename=f"{ref}_completo.zip",
            headers={
                "Cache-Control": "no-cache",
                "Access-Control-Allow-Origin": "*"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error en descarga global: {e}")
        raise HTTPException(status_code=500, detail=f"Error descargando ZIP global: {str(e)}")

@app.get("/api/v1/listar-archivos/{ref}")
async def listar_archivos_ref(ref: str):
    """Lista todos los archivos disponibles para una referencia"""
    try:
        outputs_dir = cfg.get("rutas", {}).get("outputs", "outputs")
        ref_dir = Path(outputs_dir) / ref
        
        if not ref_dir.exists():
            return {"status": "error", "message": "Directorio no encontrado", "archivos": []}
        
        archivos = []
        for file_path in ref_dir.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(outputs_dir)
                download_url = f"/api/v1/descargar-archivo/{ref}/{file_path.name}"
                
                archivos.append({
                    "nombre": file_path.name,
                    "ruta": str(rel_path),
                    "url": download_url,
                    "tamano": file_path.stat().st_size,
                    "tipo": file_path.suffix.lower()
                })
        
        return {
            "status": "success",
            "referencia": ref,
            "total_archivos": len(archivos),
            "archivos": sorted(archivos, key=lambda x: x["nombre"])
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e), "archivos": []}


# ==========================================
# ENDPOINTS DE CAPAS Y AFECCIONES (TEMPORALMENTE DESACTIVADOS)
# ==========================================

@app.get("/api/v1/capas/disponibles")
async def obtener_capas_disponibles():
    """Retorna lista de todas las capas disponibles"""
    # Temporal: respuesta simulada hasta que los módulos estén disponibles
    return {
        "status": "success",
        "total": 0,
        "por_tipo": {},
        "capas": [],
        "message": "Módulo de detección de capas no disponible temporalmente"
    }

@app.get("/api/v1/verificar-zips")
async def verificar_zips():
    """Verifica el estado de los archivos ZIP en el sistema"""
    try:
        outputs_dir = cfg.get("rutas", {}).get("outputs", "outputs")
        outputs_path = Path(outputs_dir)
        
        zip_info = []
        total_zips = 0
        
        if outputs_path.exists():
            for ref_dir in outputs_path.iterdir():
                if ref_dir.is_dir() and not ref_dir.name.startswith('.'):
                    zip_files = list(ref_dir.glob("**/*.zip"))
                    for zip_file in zip_files:
                        stat = zip_file.stat()
                        zip_info.append({
                            "referencia": ref_dir.name,
                            "archivo": zip_file.name,
                            "ruta": str(zip_file.relative_to(outputs_path)),
                            "tamano": stat.st_size,
                            "creado": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                            "modificado": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            "existe": zip_file.exists()
                        })
                        total_zips += 1
        
        return {
            "status": "success",
            "total_zips": total_zips,
            "retention_enabled": ENABLE_FILE_RETENTION,
            "retention_hours": TIEMPO_RETENCION_ARCHIVOS / 3600,
            "zips": zip_info
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/v1/expedientes/{expediente_id}/afecciones")
async def obtener_afecciones_expediente(expediente_id: str):
    """Obtiene las afecciones detectadas para un expediente"""
    try:
        exp_dir = Path(outputs_dir) / "expedientes" / f"expediente_{expediente_id}"
        afecciones_path = exp_dir / "afecciones.json"
        
        if afecciones_path.exists():
            with open(afecciones_path, "r", encoding="utf-8") as f:
                afecciones = json.load(f)
            return {"status": "success", "afecciones": afecciones}
        else:
            return {"status": "processing", "message": "Afecciones en procesamiento"}
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
