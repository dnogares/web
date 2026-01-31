import os
import sqlite3
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
try:
    import contextily as cx
except ImportError:
    cx = None
from datetime import datetime
from PIL import Image
from io import BytesIO
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from mpl_toolkits.axes_grid1.anchored_artists import AnchoredSizeBar
from pathlib import Path

class VectorAnalyzer:
    def __init__(self, capas_dir="capas", crs_objetivo="EPSG:25830", urbanismo_service=None):
        self.capas_dir = Path(capas_dir)
        self.crs_objetivo = crs_objetivo
        self.config_titulos = self.cargar_config_titulos()
        self.urbanismo_service = urbanismo_service

    def analizar(self, parcela_path, capa_input, campo_clasificacion="tipo", layer=None):
        """
        Analiza intersección entre parcela y capa vectorial
        
        Args:
            parcela_path: Ruta al archivo de la parcela (GML/GeoJSON)
            capa_input: Ruta o nombre del archivo de la capa
            campo_clasificacion: Campo para clasificar afecciones
            layer: Nombre de la capa específica (para archivos multicapa)
        """
        try:
            import os
            import warnings
            
            # Suprimir advertencias de GeoPandas
            warnings.filterwarnings('ignore', category=UserWarning)
            
            parcela_path = Path(parcela_path)
            
            # Cargar geometría parcela
            parcela_gdf = gpd.read_file(parcela_path)
            if parcela_gdf.crs != self.crs_objetivo:
                parcela_gdf = parcela_gdf.to_crs(self.crs_objetivo)
            
            geom_parcela = parcela_gdf.union_all()
            area_total = geom_parcela.area

            # Cargar la capa usando el servicio de urbanismo o directamente
            capa_gdf = None
            if self.urbanismo_service:
                capa_gdf = self.urbanismo_service.obtener_o_descargar_capa(capa_input, layer=layer)
                if capa_gdf is None:
                    return {"error": f"Capa {capa_input} no encontrada o no pudo ser descargada", "afecciones": []}
            else:
                # Método directo: buscar por nombre de archivo
                capa_path = None
                if not Path(capa_input).is_absolute():
                    # Buscar en el directorio de capas
                    extensiones = {".geojson", ".shp", ".gml"}
                    for ext in extensiones:
                        candidate_path = self.capas_dir / f"{capa_input}{ext}"
                        if candidate_path.exists():
                            capa_path = candidate_path
                            break
                
                if not capa_path or not capa_path.exists():
                    return {"error": f"Capa {capa_input} no encontrada", "afecciones": []}
                
                # Cargar capa directamente
                os.environ['OGR_GEOJSON_MAX_OBJ_SIZE'] = '50'  # 50 MB
                if layer and capa_path.suffix.lower() == '.gpkg':
                    capa_gdf = gpd.read_file(capa_path, layer=layer)
                else:
                    capa_gdf = gpd.read_file(capa_path)
            
            if capa_gdf.crs != self.crs_objetivo:
                capa_gdf = capa_gdf.to_crs(self.crs_objetivo)

            # Optimización espacial: filtrar solo geometrías que intersectan
            capa_gdf = capa_gdf[capa_gdf.intersects(geom_parcela)]
            
            if capa_gdf.empty:
                return {"afecciones": [], "total_afectado_percent": 0.0, "afecciones_detectadas": False}

            # Intersección real
            interseccion = gpd.overlay(parcela_gdf, capa_gdf, how="intersection")
            
            if interseccion.empty:
                return {"afecciones": [], "total_afectado_percent": 0.0, "afecciones_detectadas": False}

            # Calcular áreas y porcentajes
            interseccion["area_afectada"] = interseccion.geometry.area
            total_afectado = interseccion["area_afectada"].sum()
            total_percent = (total_afectado / area_total) * 100

            # Detalle por clasificación
            resultados = []
            if campo_clasificacion in interseccion.columns:
                por_clase = interseccion.groupby(campo_clasificacion)["area_afectada"].sum()
                for clase, area in por_clase.items():
                    resultados.append({
                        "clase": str(clase),
                        "area_m2": round(area, 2),
                        "porcentaje": round((area / area_total) * 100, 2)
                    })
            else:
                resultados.append({
                    "clase": "General",
                    "area_m2": round(total_afectado, 2),
                    "porcentaje": round(total_percent, 2)
                })

            return {
                "afecciones": resultados,
                "total_afectado_percent": round(total_percent, 2),
                "total_afectado_m2": round(total_afectado, 2),
                "area_parcela_m2": round(area_total, 2),
                "afecciones_detectadas": True
            }

        except Exception as e:
            print(f"Error en VectorAnalyzer.analizar: {e}")
            return {"error": str(e), "afecciones": []}

    # ------------------------------------------------------------
    # Configuración y Utilidades
    # ------------------------------------------------------------
    def cargar_config_titulos(self, csv_filename="titulos.csv"):
        # Cargar config_titulos desde la raíz de CAPAS_DIR
        csv_path = self.capas_dir / csv_filename
        if not csv_path.exists():
            # Fallback a la estructura anterior si no se encuentra en la raíz
            csv_path = self.capas_dir / "wms" / csv_filename
        
        config = {}
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path)
                for _, row in df.iterrows():
                    config[row["capa"].lower()] = {
                        "texto_previo": row.get("texto_previo", ""),
                        "texto_posterior": row.get("texto_posterior", ""),
                        "font": row.get("font", "Arial"),
                        "color": row.get("color", "black"),
                        "size": int(row.get("size", 14))
                    }
            except Exception as e:
                print(f"Error cargando titulos.csv desde {csv_path}: {e}")
        return config

    def añadir_escala(self, ax, dist_m=100):
        """Añade una barra de escala dinámica"""
        return 
        
        bar = AnchoredSizeBar(ax.transData, dist_m, f'{dist_m} m', 
                             loc='lower left', pad=0.1, borderpad=2.0, 
                             color='black', frameon=False, size_vertical=1)
        bar.set_in_layout(False) 
        ax.add_artist(bar)

    def nombre_bonito_gpkg(self, ruta):
        try:
            con = sqlite3.connect(ruta)
            cur = con.cursor()
            cur.execute("SELECT identifier, description FROM gpkg_contents LIMIT 1")
            row = cur.fetchone()
            con.close()
            if row:
                return row[0] if row[0] else row[1]
        except Exception:
            pass
        return os.path.basename(ruta)

    # ------------------------------------------------------------
    # Gestión de Leyendas y Estilos
    # ------------------------------------------------------------
    def get_legend_styling(self, capa_nombre):
        # Buscar el archivo de leyenda en la raíz de CAPAS_DIR primero
        leyenda_csv_path = self.capas_dir / f"leyenda_{capa_nombre.lower()}.csv"
        if not leyenda_csv_path.exists():
            # Fallback a la estructura anterior si no se encuentra en la raíz
            leyenda_csv_path = self.capas_dir / "wms" / f"leyenda_{capa_nombre.lower()}.csv"
        styling = {'unique': True, 'color': "blue", 'field': None, 'labels': {}, 'colors': {}} 
        
        if leyenda_csv_path.exists():
            try:
                df = pd.read_csv(leyenda_csv_path, encoding="utf-8")
                if 'CAMPO_GPKG' in df.columns:
                    styling['field'] = df['CAMPO_GPKG'].iloc[0]
                    clasif_cols = [col for col in df.columns if col.lower() in ['clasificacion', 'clase', 'clave']]
                    
                    if clasif_cols and 'color' in df.columns:
                        campo_clasif = clasif_cols[0]
                        styling['colors'] = dict(zip(df[campo_clasif].astype(str), df['color']))
                        styling['unique'] = False
                        if 'etiqueta' in df.columns:
                            styling['labels'] = dict(zip(df[campo_clasif].astype(str), df['etiqueta']))
                    return styling

                if not df.empty and 'color' in df.columns:
                    styling['color'] = df['color'].iloc[0]
                    styling['unique'] = True
            except Exception as e:
                print(f"Error en leyenda para {capa_nombre}: {e}")
        return styling

    def aplicar_leyenda(self, ax, capa):
        # Buscar el archivo de leyenda en la raíz de CAPAS_DIR primero
        leyenda_csv_path = self.capas_dir / f"leyenda_{capa['nombre'].lower()}.csv"
        if not leyenda_csv_path.exists():
            # Fallback a la estructura anterior si no se encuentra en la raíz
            leyenda_csv_path = self.capas_dir / "wms" / f"leyenda_{capa['nombre'].lower()}.csv"
        if leyenda_csv_path.exists():
            try:
                df = pd.read_csv(leyenda_csv_path, encoding="utf-8")
                handles = []
                for _, item in df.iterrows():
                    tipo = str(item["tipo"]).strip().lower()
                    color = item["color"]
                    etiq = item["etiqueta"]
                    
                    if tipo == "línea":
                        patch = Line2D([], [], color=color, linewidth=6, alpha=0.8, label=etiq)
                    elif tipo == "punto":
                        patch = Line2D([], [], marker='o', color=color, linestyle='None', markersize=8, alpha=0.8, label=etiq)
                    elif tipo == "polígono":
                        patch = Patch(facecolor=color, edgecolor='black', alpha=0.6, label=etiq)
                    else: continue
                    handles.append(patch)
                
                if handles:
                    ax.legend(handles=handles, loc='lower right', fontsize=8, ncol=2)
                    return True
            except Exception as e:
                print(f"Error al pintar leyenda: {e}")
        return False

    # ------------------------------------------------------------
    # Títulos y Mapas
    # ------------------------------------------------------------
    def aplicar_titulo(self, ax, capa, porcentaje_total=None, porcentaje_detalle=None):
        conf = self.config_titulos.get(capa["nombre"].lower(), {
            "texto_previo": "MAPA: intersección de la parcela con ",
            "texto_posterior": "", "font": "Arial", "color": "black", "size": 14
        })

        nombre_bonito = capa.get("nombre", "Capa desconocida")

        texto_titulo = f"{conf['texto_previo']}{nombre_bonito}{conf['texto_posterior']}"
        
        fig = ax.figure
        fig.text(0.01, 0.97, texto_titulo, ha="left", va="top",
                 fontname=conf["font"], color=conf["color"], fontsize=conf["size"])
             
        texto_secundario = []
        if porcentaje_total is not None:
            texto_secundario.append(f"Afección Total: {porcentaje_total:.2f}%")
        if porcentaje_detalle:
            detalle_str = ", ".join([f"{k}: {v:.2f}%" for k, v in porcentaje_detalle.items() if v > 0.01])
            if detalle_str: texto_secundario.append(f"Detalle: {detalle_str}")
        
        if texto_secundario:
            fig.text(0.01, 0.94, " | ".join(texto_secundario), ha="left", va="top",
                     fontname=conf["font"], color=conf["color"], fontsize=conf["size"]-2)

    # ------------------------------------------------------------
    # Procesamiento Principal (Compatibilidad batch)
    # ------------------------------------------------------------
    def procesar_parcelas(self, capas_wms):
        """Procesa los archivos en datos_origen contra las capas configuradas"""
        origen_dir = Path("datos_origen")
        if not origen_dir.exists(): return

        for archivo_parcela in origen_dir.iterdir():
            if not archivo_parcela.suffix.lower() in [".shp", ".gml", ".geojson", ".json", ".kml"]:
                continue
                
            try:
                nombre_subcarpeta = f"{archivo_parcela.stem}_{datetime.now().strftime('%Y%m%d_%H%M')}"
                carpeta_res = Path("resultados") / nombre_subcarpeta
                carpeta_res.mkdir(parents=True, exist_ok=True)
                
                resultados_csv = []

                for capa_cfg in capas_wms:
                    if not capa_cfg.get("gpkg"): continue
                    
                    # Llamar al metodo analizar
                    res = self.analizar(
                        parcela_path=archivo_parcela,
                        capa_input=capa_cfg["nombre"] # Ahora se espera el nombre de la capa
                    )
                    
                    if res.get("afecciones_detectadas"):
                        perc = res.get("total_afectado_percent", 0)
                        resultados_csv.append({
                            "parcela": archivo_parcela.name, 
                            "capa": capa_cfg["nombre"], 
                            "porcentaje": perc
                        })
                    else:
                        resultados_csv.append({
                            "parcela": archivo_parcela.name, 
                            "capa": capa_cfg["nombre"], 
                            "porcentaje": 0
                        })

                if resultados_csv:
                    pd.DataFrame(resultados_csv).to_excel(carpeta_res / "resultados.xlsx", index=False)

            except Exception as e:
                print(f"Error general procesando {archivo_parcela}: {e}")
