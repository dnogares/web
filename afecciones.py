import os
import sys
import json
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import contextily as cx
from datetime import datetime
from pathlib import Path

from typing import List, Dict, Any

# Configuración simplificada para el test
CONFIG_TITULOS = {
    "Red Natura 2000": "ANÁLISIS DE AFECCIÓN: RED NATURA 2000",
    "Vías Pecuarias": "ANÁLISIS DE AFECCIÓN: VÍAS PECUARIAS",
    "Montes Públicos": "ANÁLISIS DE AFECCIÓN: MONTES PÚBLICOS",
    "Caminos Naturales": "ANÁLISIS DE AFECCIÓN: CAMINOS NATURALES"
}

def get_capas_dir():
    """Determina el directorio de capas según el entorno (EasyPanel/Local)"""
    # 1. Variable de entorno explícita
    env_path = os.getenv("CAPAS_DIR")
    if env_path and os.path.exists(env_path):
        return env_path
    
    # 2. Volumen persistente EasyPanel
    if os.path.exists("/app/capas"):
        return "/app/capas"
        
    # 3. Ruta de red para pruebas locales (Windows)
    z_path = r"Z:\compartidaconeasypanel\files3\proyecto_gis\capas"
    if os.path.exists(z_path):
        return z_path
        
    # 4. Fallback local
    return "capas"

def listar_capas_locales():
    """Busca capas vectoriales en el directorio configurado"""
    capas_dir = get_capas_dir()
    capas = []
    print(f"📂 Buscando capas en: {capas_dir}")
    
    if os.path.exists(capas_dir):
        for root, dirs, files in os.walk(capas_dir):
            for f in files:
                # Añadir soporte para .fgb (FlatGeobuf)
                if f.lower().endswith(('.shp', '.gpkg', '.geojson', '.kml', '.fgb')):
                    capas.append(os.path.join(root, f))
    return capas

def listar_capas_wfs(csv_path):
    """Carga configuración de capas WFS desde CSV"""
    if csv_path and os.path.exists(csv_path):
        try:
            return pd.read_csv(csv_path).to_dict('records')
        except Exception as e:
            print(f"Error leyendo WFS CSV: {e}")
            return []
    return []

def listar_capas_wms(csv_path):
    """Carga configuración de capas WMS desde CSV"""
    # Ajustar ruta si estamos en EasyPanel o estructura diferente
    if csv_path and not os.path.exists(csv_path):
        # Intentar buscar en el directorio de capas o config
        posibles = [
            os.path.join("config", os.path.basename(csv_path)),
            os.path.join(get_capas_dir(), "wms", os.path.basename(csv_path))
        ]
        for p in posibles:
            if os.path.exists(p):
                csv_path = p
                break
                
    if csv_path and os.path.exists(csv_path):
        try:
            return pd.read_csv(csv_path).to_dict('records')
        except Exception as e:
            print(f"Error leyendo WMS CSV: {e}")
            return []
    return []

def cargar_config_titulos():
    """Devuelve la configuración de títulos"""
    return CONFIG_TITULOS

from gis_db import GISDatabase


def _load_vectoriales_gis_from_ajustes() -> List[str]:
    try:
        if os.path.exists("ajustes_config.json"):
            with open("ajustes_config.json", "r", encoding="utf-8") as f:
                cfg = json.load(f)
            capas = cfg.get("vectoriales_gis", [])
            if isinstance(capas, list):
                return [str(x) for x in capas if x]
    except Exception:
        pass
    return []

def procesar_parcelas(capas_locales, capas_wfs, capas_wms, crs_objetivo, config_titulos, ruta_input=None, output_dir_base="resultados"):
    """
    Versión refactorizada para usar PostGIS.
    Ignora capas_locales/wms/wfs si se detecta conexión a la DB.
    """
    db = GISDatabase()
    use_db = db.test_connection()
    
    if use_db:
        print("🔗 Usando base de datos PostGIS para análisis de afecciones")

        # 1) Si hay selección en Ajustes, usar SOLO esas capas
        seleccion = _load_vectoriales_gis_from_ajustes()
        selected_pairs: List[Dict[str, str]] = []
        for full_name in seleccion:
            if "." in full_name:
                schema, table = full_name.split(".", 1)
                selected_pairs.append({"schema": schema, "name": table, "full_name": full_name})

        if selected_pairs:
            tablas_db = selected_pairs
            print(f"📊 Usando {len(tablas_db)} capas seleccionadas en Ajustes")
        else:
            # 2) Fallback: usar todas las capas del esquema afecciones
            tablas_db = db.get_available_layers(schemas=["afecciones"])
            print(f"📊 {len(tablas_db)} capas detectadas en el esquema afecciones")
    else:
        print("⚠️ No hay conexión a DB GIS. Usando modo tradicional (SHP/WMS)")
        # Lógica original o simplificada si no hay DB

    archivos_a_procesar = []
    if ruta_input and os.path.exists(ruta_input):
        archivos_a_procesar.append(ruta_input)
    else:
        if os.path.exists("datos_origen"):
            for archivo in os.listdir("datos_origen"):
                if archivo.lower().endswith((".shp", ".gml", ".geojson", ".json", ".kml")):
                    archivos_a_procesar.append(os.path.join("datos_origen", archivo))

    listado_resultados_finales = []

    for ruta_parcela in archivos_a_procesar:
        archivo_parcela = os.path.basename(ruta_parcela)
        try:
            parcela = gpd.read_file(ruta_parcela).to_crs(epsg=4326)
            geom_parcela_wkt = parcela.geometry.unary_union.wkt

            nombre_base = os.path.splitext(archivo_parcela)[0]
            carpeta_resultados = os.path.join(output_dir_base, f"{nombre_base}_analisis")
            os.makedirs(carpeta_resultados, exist_ok=True)

            resultados = []

            if use_db:
                # Análisis contra cada tabla del esquema afecciones
                for tabla in tablas_db:
                    try:
                        schema = tabla.get("schema", "afecciones") if isinstance(tabla, dict) else "afecciones"
                        table = tabla.get("name") if isinstance(tabla, dict) else str(tabla)
                        if not table:
                            continue

                        # Consultar directamente la intersección en la base de datos
                        interseccion_gdf = db.query_intersection(schema, table, geom_parcela_wkt)
                        
                        if interseccion_gdf.empty:
                            continue

                        # Proyectar a un CRS métrico para calcular áreas
                        parcela_proj = parcela.to_crs(crs_objetivo)
                        interseccion_proj = interseccion_gdf.to_crs(crs_objetivo)
                        
                        # Calcular el área de la intersección real
                        area_interseccion_gdf = gpd.overlay(parcela_proj, interseccion_proj, how="intersection")

                        if not area_interseccion_gdf.empty:
                            area_parcela = parcela_proj.area.sum()
                            area_afectada = area_interseccion_gdf.area.sum()
                            perc = (area_afectada / area_parcela) * 100 if area_parcela > 0 else 0
                            
                            if perc > 0.01: # Umbral mínimo de relevancia
                                capa_label = tabla.get("full_name") if isinstance(tabla, dict) and tabla.get("full_name") else table
                                resultados.append({
                                    "parcela": archivo_parcela,
                                    "capa": capa_label,
                                    "porcentaje": round(perc, 2),
                                    "origen": "PostGIS (Intersección Directa)"
                                })
                                print(f"  ✓ Afección hallada: {capa_label} ({perc:.2f}%)")
                                
                                # Generar mapa para esta afección
                                fig, ax = plt.subplots(figsize=(8, 6))
                                bbox = parcela.total_bounds
                                cx_min, cy_min, cx_max, cy_max = bbox
                                margin = 0.002
                                ax.set_xlim(cx_min-margin, cx_max+margin)
                                ax.set_ylim(cy_min-margin, cy_max+margin)
                                
                                # Capa de afección completa para contexto
                                interseccion_gdf.to_crs(epsg=4326).plot(ax=ax, color='orange', alpha=0.5, label=f'Afección ({tabla})')
                                # Parcela analizada
                                parcela.plot(ax=ax, facecolor="none", edgecolor="red", linewidth=2, label='Parcela')
                                # Área exacta de intersección
                                area_interseccion_gdf.to_crs(epsg=4326).plot(ax=ax, color='purple', alpha=0.7, label='Área Afectada')
                                
                                try:
                                    cx.add_basemap(ax, crs=4326, source=cx.providers.OpenStreetMap.Mapnik)
                                except: pass
                                
                                ax.legend()
                                ax.set_title(f"Afección: {capa_label} ({perc:.2f}%)")
                                safe_name = str(capa_label).replace("/", "_").replace("\\", "_").replace(":", "_")
                                plt.savefig(os.path.join(carpeta_resultados, f"mapa_{safe_name}.jpg"), bbox_inches='tight')
                                plt.close()

                    except Exception as e:
                        print(f"Error procesando tabla {tabla}: {e}")

            # Guardar reporte CSV
            pd.DataFrame(resultados).to_csv(os.path.join(carpeta_resultados, "afecciones_db.csv"), index=False)
            
            mapas_list = [os.path.join(carpeta_resultados, f) for f in os.listdir(carpeta_resultados) if f.endswith(".jpg")]
            listado_resultados_finales.append({
                "parcela": archivo_parcela,
                "carpeta": carpeta_resultados,
                "mapas": mapas_list,
                "datos": resultados
            })

        except Exception as e:
            print(f"Error procesando {archivo_parcela}: {e}")

    return listado_resultados_finales

if __name__ == "__main__":
    # Test simple
    pass
