from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional
import csv
import tempfile
import sys
import io
import warnings
import psutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import requests
import xml.etree.ElementTree as ET
import geopandas as gpd
import contextily as cx
import fiona
from PIL import Image
from io import BytesIO
from shapely.geometry import box

# Ignorar advertencias de geometrías medidas (M) para limpiar la consola
warnings.filterwarnings("ignore", category=UserWarning)

# Configurar salida estándar a UTF-8 para evitar errores de emojis en Windows
if sys.stdout and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN GLOBAL
# ═══════════════════════════════════════════════════════════════════════════

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0"
)

# Habilitar soporte para archivos KML en Fiona
if 'KML' not in fiona.supported_drivers:
    fiona.drvsupport.supported_drivers['KML'] = 'rw'

# ═══════════════════════════════════════════════════════════════════════════
# CLASE DE DATOS: PARCELA
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ParcelaData:
    """
    Representa una parcela catastral con toda su información asociada.
    
    Attributes:
        refcat: Referencia catastral (identificador único)
        provincia: Código de provincia (primeros 2 dígitos de refcat)
        geometria: Lista de coordenadas (lon, lat) que definen el polígono
        info_catastral: Diccionario con m2, latitud, longitud
        recintos_sigpac: Lista de recintos SIGPAC asociados
        afecciones: Lista de afecciones detectadas
        rutas: Diccionario con rutas a archivos generados (xml, pdf, kml, png)
    """
    refcat: str
    provincia: str = field(init=False)
    geometria: List[Tuple[float, float]] = field(default_factory=list)
    info_catastral: dict = field(default_factory=dict)
    recintos_sigpac: List[dict] = field(default_factory=list)
    afecciones: List[dict] = field(default_factory=list)
    rutas: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Extrae automáticamente la provincia de la referencia catastral."""
        self.provincia = self.refcat[:2]

    @property
    def poligono(self) -> str:
        """Extrae el código de polígono (caracteres 7-9)."""
        return self.refcat[6:9]

    @property
    def parcela(self) -> str:
        """Extrae el código de parcela (caracteres 10-14)."""
        return self.refcat[9:14]

    def has_geometry(self) -> bool:
        """Verifica si la parcela tiene geometría cargada."""
        return bool(self.geometria)

    def actualizar_geometria(self, coords: List[Tuple[float, float]], superficie: float) -> None:
        """
        Actualiza la geometría y la información catastral de la parcela.
        
        Args:
            coords: Lista de tuplas (longitud, latitud)
            superficie: Superficie en metros cuadrados
        """
        self.geometria = coords
        if coords:
            self.info_catastral = {
                "m2": superficie,
                "latitud": coords[0][1],  # Primera coordenada como referencia
                "longitud": coords[0][0],
            }

    def registro_tabla(self) -> dict:
        """
        Genera un registro para exportación a tabla (Excel/CSV).
        
        Returns:
            Diccionario con campos: Referencia, Polígono, Parcela, m2, Ha, Latitud, Longitud
        """
        m2 = self.info_catastral.get("m2", 0)
        return {
            "Referencia": self.refcat,
            "Polígono": self.poligono,
            "Parcela": self.parcela,
            "m2": m2,
            "Ha": round(m2 / 10000, 4),
            "Latitud": self.info_catastral.get("latitud"),
            "Longitud": self.info_catastral.get("longitud"),
        }


# ═══════════════════════════════════════════════════════════════════════════
# CLASE PRINCIPAL: ORQUESTADOR DEL PIPELINE
# ═══════════════════════════════════════════════════════════════════════════

class OrquestadorPipeline:
    """
    Orquestador principal que ejecuta el proceso completo de 19 pasos.
    
    El proceso procesa referencias catastrales desde archivos .txt en INPUTS
    y genera todos los productos cartográficos en OUTPUTS.
    """
    
    def __init__(
        self, 
        base_dir: Path,
        fuentes_dir: Optional[Path] = None,
        progress_callback: Optional[callable] = None,
        geometry_callback: Optional[callable] = None
    ) -> None:
        """
        Inicializa el orquestador y crea las carpetas necesarias.
        
        Args:
            base_dir: Directorio base del proyecto (donde están INPUTS y OUTPUTS)
            fuentes_dir: Directorio de FUENTES (por defecto /app/FUENTES en producción)
            progress_callback: Función para reportar progreso (callable)
            geometry_callback: Función para reportar geometrías encontradas (callable)
        """
        self.base_dir = base_dir
        self.inputs = base_dir / "INPUTS"
        self.outputs = base_dir / "OUTPUTS"
        
        # FUENTES puede estar en /app/FUENTES (Easypanel) o local
        if fuentes_dir:
            self.fuentes = fuentes_dir
        else:
            # Intentar usar /app/FUENTES si existe, sino usar local
            self.fuentes = Path("/app/FUENTES") if Path("/app/FUENTES").exists() else base_dir / "FUENTES"
        
        self.carpeta_afecciones = self.fuentes / "CAPAS_gpkg" / "afecciones"
        
        # Callback para progreso
        self.progress_callback = progress_callback or (lambda x: print(x))
        self.geometry_callback = geometry_callback
        
        # Sesión HTTP reutilizable para eficiencia
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        
        # Crear estructura de directorios
        self.inputs.mkdir(parents=True, exist_ok=True)
        self.outputs.mkdir(parents=True, exist_ok=True)
        self.carpeta_afecciones.mkdir(parents=True, exist_ok=True)
        
        self.log(f"📂 Base: {self.base_dir}")
        self.log(f"📦 Fuentes: {self.fuentes}")

    def log(self, mensaje: str) -> None:
        """
        Envía un mensaje al callback de progreso.
        
        Args:
            mensaje: Mensaje a reportar
        """
        if self.progress_callback:
            self.progress_callback(mensaje)

    def _verificar_memoria(self) -> None:
        """Verifica si el uso de memoria supera el límite de seguridad (70%)."""
        mem = psutil.virtual_memory()
        if mem.percent >= 70.0:
            msg = f"🛑 ABORTANDO POR SEGURIDAD: Uso de RAM crítico ({mem.percent}%)"
            self.log(msg)
            raise MemoryError(msg)

    def procesar_archivo_txt(self, txt_path: Path) -> Optional[Path]:
        """
        Procesa un archivo .txt específico con referencias catastrales.
        
        Args:
            txt_path: Ruta al archivo .txt con referencias catastrales
            
        Returns:
            Path a la carpeta de resultados o None si falló
        """
        self.log(f"{'═'*80}")
        self.log(f"📄 PROCESANDO: {txt_path.name}")
        self.log(f"{'═'*80}")
        
        # PASO 1: Leer referencias catastrales
        referencias = self._leer_referencias(txt_path)
        if not referencias:
            self.log(f"⚠️ {txt_path.name} está vacío o no contiene RCs válidos.")
            return None

        self.log(f"✅ {len(referencias)} referencias catastrales leídas")
        
        self._verificar_memoria()
        
        # Crear carpeta de salida con timestamp
        carpeta = self._crear_subcarpeta(txt_path.stem)
        self.log(f"📁 Carpeta de salida: {carpeta.name}")
        
        # PASOS 2-3: Descargar y procesar datos catastrales
        self.log(f"{'─'*80}")
        self.log(f"FASE 1: ADQUISICIÓN DE DATOS")
        self.log(f"{'─'*80}")
        parcelas = self._procesar_referencias(referencias, carpeta)
        
        if not parcelas:
            self.log(f"⚠️ Ninguna referencia de {txt_path.name} pudo completarse.")
            return None

        self.log(f"✅ {len(parcelas)} parcelas procesadas correctamente")
        
        self._verificar_memoria()

        # FASE 2: GENERACIÓN VECTORIAL (Pasos 4-5)
        self.log(f"{'─'*80}")
        self.log(f"FASE 2: GENERACIÓN VECTORIAL")
        self.log(f"{'─'*80}")
        self._generar_kml(carpeta, parcelas)
        self._generar_png(carpeta, parcelas)
        
        # FASE 3: EXPORTACIÓN TABULAR (Paso 6)
        self.log(f"{'─'*80}")
        self.log(f"FASE 3: EXPORTACIÓN TABULAR")
        self.log(f"{'─'*80}")
        self._crear_tablas(carpeta, parcelas)
        
        # FASE 4: DOCUMENTACIÓN (Paso 7)
        self.log(f"{'─'*80}")
        self.log(f"FASE 4: DOCUMENTACIÓN")
        self.log(f"{'─'*80}")
        self._generar_log_expediente(carpeta, parcelas)
        
        # FASE 5: ANÁLISIS ESPACIAL (Paso 8)
        # self.log(f"{'─'*80}")
        # self.log(f"FASE 5: ANÁLISIS ESPACIAL (OMITIDA)")
        # self.log(f"{'─'*80}")
        # self._procesar_afecciones(carpeta)
        
        self._verificar_memoria()
        
        # FASE 6: PLANOS DE EMPLAZAMIENTO BÁSICOS (Pasos 9-10)
        self.log(f"{'─'*80}")
        self.log(f"FASE 6: PLANOS DE EMPLAZAMIENTO BÁSICOS")
        self.log(f"{'─'*80}")
        self._generar_plano_emplazamiento(carpeta)
        self._generar_plano_ortofoto(carpeta)
        
        self._verificar_memoria()
        
        # FASE 7: PLANOS CATASTRALES (Paso 11)
        self.log(f"{'─'*80}")
        self.log(f"FASE 7: PLANOS CATASTRALES")
        self.log(f"{'─'*80}")
        self._generar_plano_catastral(carpeta)
        
        # FASE 8: PLANOS IGN DETALLADOS (Paso 12)
        self.log(f"{'─'*80}")
        self.log(f"FASE 8: PLANOS IGN DETALLADOS")
        self.log(f"{'─'*80}")
        self._generar_planos_ign(carpeta)
        
        # FASE 9: PLANOS DE LOCALIZACIÓN PROVINCIAL (Paso 13)
        self.log(f"{'─'*80}")
        self.log(f"FASE 9: PLANOS DE LOCALIZACIÓN PROVINCIAL")
        self.log(f"{'─'*80}")
        self._generar_planos_provinciales(carpeta)
        
        # FASE 10: PLANOS CARTOGRÁFICOS HISTÓRICOS (Paso 14)
        self.log(f"{'─'*80}")
        self.log(f"FASE 10: PLANOS CARTOGRÁFICOS HISTÓRICOS")
        self.log(f"{'─'*80}")
        self._generar_planos_historicos(carpeta)
        
        # FASE 11: PLANOS TEMÁTICOS AMBIENTALES (Pasos 16-17)
        self.log(f"{'─'*80}")
        self.log(f"FASE 11: PLANOS TEMÁTICOS AMBIENTALES")
        self.log(f"{'─'*80}")
        self._generar_plano_pendientes(carpeta)
        
        self._verificar_memoria()
        self._generar_plano_natura2000(carpeta)
        
        # FASE 12: PLANOS DE PROTECCIÓN AMBIENTAL (Pasos 18-19)
        self.log(f"{'─'*80}")
        self.log(f"FASE 12: PLANOS DE PROTECCIÓN AMBIENTAL")
        self.log(f"{'─'*80}")
        self._generar_plano_montes_publicos(carpeta)
        self._generar_plano_vias_pecuarias(carpeta)
        
        # FASE 13: INFORMES SIGPAC (Paso 20)
        self.log(f"{'─'*80}")
        self.log(f"FASE 13: INFORMES SIGPAC")
        self.log(f"{'─'*80}")
        self.generarinformessigpac(carpeta, parcelas)
        
        self.log(f"{'═'*80}")
        self.log(f"✅ PROCESO COMPLETO FINALIZADO: {txt_path.name}")
        self.log(f"{'═'*80}")
        
        return carpeta


    def generarinformessigpac(self, carpeta: Path, parcelas: List[ParcelaData]) -> None:
        """
        PASO 20: Obtiene información de recintos SIGPAC y genera enlaces a informes PDF.
        
        NOTA: El servicio SIGPAC requiere JavaScript para generar PDFs.
        Este método genera:
        - Excel con datos completos de recintos y URLs
        - HTML con enlaces directos clickeables para descargar PDFs
        
        Args:
            carpeta: Carpeta donde guardar los informes
            parcelas: Lista de parcelas procesadas
        """
        self.log("="*80)
        self.log("FASE 13: INFORMES SIGPAC")
        self.log("="*80)
        self.log("Paso 20: Obteniendo información de recintos SIGPAC...")
        
        carpeta_sigpac = carpeta / "SIGPAC-INFORMES"
        carpeta_sigpac.mkdir(parents=True, exist_ok=True)
        
        resumen_recintos = []
        html_content = []
        
        html_content.append("""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Enlaces Informes SIGPAC</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
        h1 { color: #2c3e50; }
        .recinto { background: white; padding: 15px; margin: 10px 0; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .recinto h3 { margin-top: 0; color: #27ae60; }
        .info { margin: 5px 0; }
        .btn { display: inline-block; padding: 10px 20px; background: #3498db; color: white; text-decoration: none; border-radius: 5px; margin-top: 10px; }
        .btn:hover { background: #2980b9; }
        .label { font-weight: bold; color: #555; }
    </style>
</head>
<body>
    <h1>📄 Informes SIGPAC - Enlaces de Descarga</h1>
    <p>Haz clic en los botones para abrir cada informe PDF en el visor SIGPAC.</p>
""")
        
        for parcela in parcelas:
            if not parcela.has_geometry():
                self.log(f"⚠️  {parcela.refcat}: Sin geometría, omitiendo")
                continue
                
            try:
                # 1. Obtener bbox de la parcela
                lons, lats = zip(*parcela.geometria)
                minx, maxx = min(lons), max(lons)
                miny, maxy = min(lats), max(lats)
                bbox = f"{minx},{miny},{maxx},{maxy}"
                
                self.log(f"🔍 {parcela.refcat}: Consultando SIGPAC (bbox={bbox[:30]}...)")
                
                # 2. Consultar OGC API Features de SIGPAC
                url_recintos = "https://sigpac-hubcloud.es/ogcapi/collections/recintos/items"
                params = {
                    "f": "json",
                    "bbox": bbox,
                    "limit": 100
                }
                
                response = self.session.get(url_recintos, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
                
                features = data.get("features", [])
                if not features:
                    self.log(f"   ℹ️  No se encontraron recintos SIGPAC")
                    continue
                    
                self.log(f"   ✅ Encontrados {len(features)} recintos SIGPAC")
                
                # 3. Procesar cada recinto encontrado
                for idx, feature in enumerate(features, 1):
                    props = feature.get("properties", {})
                    
                    # Extraer identificadores del recinto SIGPAC
                    provincia = props.get("provincia", "")
                    municipio = props.get("municipio", "")
                    agregado = props.get("agregado", "0")
                    zona = props.get("zona", "0")
                    poligono = props.get("poligono", "")
                    parcela_sigpac = props.get("parcela", "")
                    recinto = props.get("recinto", "")
                    
                    # Información adicional
                    uso_sigpac = props.get("uso_sigpac", "")
                    coef_regadio = props.get("coeficiente_regadio", "")
                    superficie = props.get("superficie", 0)
                    pendiente_media = props.get("pendiente_media", "")
                    
                    if not all([provincia, municipio, poligono, parcela_sigpac, recinto]):
                        self.log(f"   ⚠️  Recinto {idx}: Datos incompletos, omitiendo")
                        continue
                    
                    # 4. Construir referencia SIGPAC (formato: prov:mun:agr:zona:pol:par:rec)
                    ref_sigpac = f"{provincia}:{municipio}:{agregado}:{zona}:{poligono}:{parcela_sigpac}:{recinto}"
                    url_pdf = f"https://sigpac-hubcloud.es/salidasgraficassigpac/?recinto/{provincia}/{municipio}/{agregado}/{zona}/{poligono}/{parcela_sigpac}/{recinto}"
                    
                    self.log(f"   📄 Recinto {idx}: {ref_sigpac} - {uso_sigpac} ({round(superficie/10000, 4)} ha)")
                    
                    # 5. Guardar información para resumen
                    resumen_recintos.append({
                        "RefCatastral": parcela.refcat,
                        "Provincia": provincia,
                        "Municipio": municipio,
                        "Agregado": agregado,
                        "Zona": zona,
                        "Polígono": poligono,
                        "Parcela_SIGPAC": parcela_sigpac,
                        "Recinto": recinto,
                        "Ref_SIGPAC": ref_sigpac,
                        "Uso_SIGPAC": uso_sigpac,
                        "Coef_Regadío": coef_regadio,
                        "Pendiente_Media": pendiente_media,
                        "Superficie_m2": superficie,
                        "Superficie_Ha": round(superficie / 10000, 4),
                        "URL_PDF": url_pdf
                    })
                    
                    # 6. Añadir al HTML
                    html_content.append(f"""
    <div class="recinto">
        <h3>📍 Recinto SIGPAC: {ref_sigpac}</h3>
        <div class="info"><span class="label">Ref. Catastral:</span> {parcela.refcat}</div>
        <div class="info"><span class="label">Uso:</span> {uso_sigpac}</div>
        <div class="info"><span class="label">Superficie:</span> {round(superficie/10000, 4)} ha ({superficie} m²)</div>
        <div class="info"><span class="label">Coef. Regadío:</span> {coef_regadio}</div>
        <div class="info"><span class="label">Pendiente Media:</span> {pendiente_media}</div>
        <a href="{url_pdf}" target="_blank" class="btn">🔗 Abrir Informe PDF</a>
    </div>
""")
                    
                    # 7. Actualizar objeto parcela
                    parcela.recintos_sigpac.append({
                        "provincia": provincia,
                        "municipio": municipio,
                        "poligono": poligono,
                        "parcela": parcela_sigpac,
                        "recinto": recinto,
                        "ref_sigpac": ref_sigpac,
                        "uso": uso_sigpac,
                        "superficie_ha": round(superficie / 10000, 4),
                        "url_pdf": url_pdf
                    })
                        
            except Exception as e:
                self.log(f"❌ Error procesando {parcela.refcat}: {str(e)}")
                import traceback
                self.log(traceback.format_exc()[:300])
        
        # 8. Cerrar HTML
        html_content.append("""
</body>
</html>
""")
        
        # 9. Guardar archivos
        if resumen_recintos:
            # Excel con datos completos
            df_resumen = pd.DataFrame(resumen_recintos)
            excel_path = carpeta / "SIGPAC-RECINTOS-RESUMEN.xlsx"
            df_resumen.to_excel(excel_path, index=False, engine='openpyxl')
            
            # HTML con enlaces clickeables
            html_path = carpeta / "SIGPAC-ENLACES-PDF.html"
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(''.join(html_content))
            
            self.log("="*80)
            self.log(f"✅ INFORMES SIGPAC PROCESADOS: {len(resumen_recintos)} recintos")
            self.log(f"📊 Resumen Excel: {excel_path.name}")
            self.log(f"🌐 HTML generado: {html_path.name}")
            self.log(f"   Abre el HTML para acceder a todos los PDFs con un clic")
            self.log("="*80)
        else:
            self.log("⚠️  No se encontraron recintos SIGPAC para ninguna parcela")


    # ═══════════════════════════════════════════════════════════════════════
    # MÉTODO PRINCIPAL: EJECUTAR PIPELINE COMPLETO
    # ═══════════════════════════════════════════════════════════════════════

    def run(self) -> None:
        """
        Ejecuta el pipeline completo para todos los archivos .txt encontrados en INPUTS.
        
        Para cada archivo .txt:
            1. Lee las referencias catastrales
            2. Descarga datos (XML, PDF)
            3. Genera productos vectoriales (KML, PNG)
            4. Crea tablas de datos
            5. Genera log y análisis
            6. Produce todos los planos cartográficos (19 pasos en total)
        """
        archivos_txt = sorted(self.inputs.glob("*.txt"))
        
        if not archivos_txt:
            print(f"🔍 No hay archivos .txt en {self.inputs}. Añade una lista de RCs y vuelve a intentar.")
            return

        # Procesar cada archivo de texto
        for txt_path in archivos_txt:
            print(f"\n{'═'*80}")
            print(f"📄 PROCESANDO: {txt_path.name}")
            print(f"{'═'*80}\n")
            
            # PASO 1: Leer referencias catastrales
            referencias = self._leer_referencias(txt_path)
            if not referencias:
                print(f"⚠️ {txt_path.name} está vacío o no contiene RCs válidos.")
                continue

            print(f"✅ {len(referencias)} referencias catastrales leídas\n")
            
            # Crear carpeta de salida con timestamp
            carpeta = self._crear_subcarpeta(txt_path.stem)
            print(f"📁 Carpeta de salida: {carpeta.name}\n")
            
            # PASOS 2-3: Descargar y procesar datos catastrales
            print(f"{'─'*80}")
            print(f"FASE 1: ADQUISICIÓN DE DATOS")
            print(f"{'─'*80}")
            parcelas = self._procesar_referencias(referencias, carpeta)
            
            if not parcelas:
                print(f"⚠️ Ninguna referencia de {txt_path.name} pudo completarse.")
                continue

            print(f"\n✅ {len(parcelas)} parcelas procesadas correctamente\n")

            # FASE 2: GENERACIÓN VECTORIAL (Pasos 4-5)
            print(f"{'─'*80}")
            print(f"FASE 2: GENERACIÓN VECTORIAL")
            print(f"{'─'*80}")
            self._generar_kml(carpeta, parcelas)
            self._generar_png(carpeta, parcelas)
            
            # FASE 3: EXPORTACIÓN TABULAR (Paso 6)
            print(f"\n{'─'*80}")
            print(f"FASE 3: EXPORTACIÓN TABULAR")
            print(f"{'─'*80}")
            self._crear_tablas(carpeta, parcelas)
            
            # FASE 4: DOCUMENTACIÓN (Paso 7)
            print(f"\n{'─'*80}")
            print(f"FASE 4: DOCUMENTACIÓN")
            print(f"{'─'*80}")
            self._generar_log_expediente(carpeta, parcelas)
            
            # FASE 5: ANÁLISIS ESPACIAL (Paso 8)
            print(f"\n{'─'*80}")
            print(f"FASE 5: ANÁLISIS ESPACIAL")
            print(f"{'─'*80}")
            self._procesar_afecciones(carpeta)
            
            # FASE 6: PLANOS DE EMPLAZAMIENTO BÁSICOS (Pasos 9-10)
            print(f"\n{'─'*80}")
            print(f"FASE 6: PLANOS DE EMPLAZAMIENTO BÁSICOS")
            print(f"{'─'*80}")
            self._generar_plano_emplazamiento(carpeta)
            self._generar_plano_ortofoto(carpeta)
            
            # FASE 7: PLANOS CATASTRALES (Paso 11)
            print(f"\n{'─'*80}")
            print(f"FASE 7: PLANOS CATASTRALES")
            print(f"{'─'*80}")
            self._generar_plano_catastral(carpeta)
            
            # FASE 8: PLANOS IGN DETALLADOS (Paso 12)
            print(f"\n{'─'*80}")
            print(f"FASE 8: PLANOS IGN DETALLADOS")
            print(f"{'─'*80}")
            self._generar_planos_ign(carpeta)
            
            # FASE 9: PLANOS DE LOCALIZACIÓN PROVINCIAL (Paso 13)
            print(f"\n{'─'*80}")
            print(f"FASE 9: PLANOS DE LOCALIZACIÓN PROVINCIAL")
            print(f"{'─'*80}")
            self._generar_planos_provinciales(carpeta)
            
            # FASE 10: PLANOS CARTOGRÁFICOS HISTÓRICOS (Paso 14)
            print(f"\n{'─'*80}")
            print(f"FASE 10: PLANOS CARTOGRÁFICOS HISTÓRICOS")
            print(f"{'─'*80}")
            self._generar_planos_historicos(carpeta)
            
            # FASE 11: PLANOS TEMÁTICOS AMBIENTALES (Pasos 16-17)
            print(f"\n{'─'*80}")
            print(f"FASE 11: PLANOS TEMÁTICOS AMBIENTALES")
            print(f"{'─'*80}")
            self._generar_plano_pendientes(carpeta)
            self._generar_plano_natura2000(carpeta)
            
            # FASE 12: PLANOS DE PROTECCIÓN AMBIENTAL (Pasos 18-19) 🆕
            print(f"\n{'─'*80}")
            print(f"FASE 12: PLANOS DE PROTECCIÓN AMBIENTAL 🆕")
            print(f"{'─'*80}")
            self._generar_plano_montes_publicos(carpeta)
            self._generar_plano_vias_pecuarias(carpeta)
            
            # FASE 13: INFORMES SIGPAC (Paso 20)
            print(f"\n{'─'*80}")
            print(f"FASE 13: INFORMES SIGPAC")
            print(f"{'─'*80}")
            self.generarinformessigpac(carpeta, parcelas)
            
            print(f"\n{'═'*80}")
            print(f"✅ PIPELINE COMPLETO FINALIZADO: {txt_path.name}")
            print(f"{'═'*80}\n")

    # ═══════════════════════════════════════════════════════════════════════
    # PASO 1: LECTURA Y ORGANIZACIÓN
    # ═══════════════════════════════════════════════════════════════════════
    
    def _leer_referencias(self, ruta_txt: Path) -> List[str]:
        """
        Lee referencias catastrales desde un archivo de texto.
        
        Formato esperado: Una referencia catastral por línea (mínimo 14 caracteres).
        
        Args:
            ruta_txt: Ruta al archivo .txt con las referencias
            
        Returns:
            Lista de referencias catastrales en mayúsculas
        """
        referencias: List[str] = []
        with ruta_txt.open("r", encoding="utf-8") as handle:
            for linea in handle:
                texto = linea.strip().upper()
                if len(texto) >= 14:
                    referencias.append(texto)
        return referencias

    def _crear_subcarpeta(self, nombre_base: str) -> Path:
        """
        Crea una subcarpeta en OUTPUTS con timestamp para los resultados.
        
        Formato: [nombre_base]-[YYYYMMDD-HHMMSS]
        
        Args:
            nombre_base: Nombre base del archivo (sin extensión)
            
        Returns:
            Path de la carpeta creada
        """
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        nombre = f"{nombre_base}-{timestamp}".replace(" ", "_")
        carpeta = self.outputs / nombre
        carpeta.mkdir(parents=True, exist_ok=True)
        return carpeta

    # ═══════════════════════════════════════════════════════════════════════
    # PASOS 2-3: ADQUISICIÓN (XML + PDF)
    # ═══════════════════════════════════════════════════════════════════════
    
    def _procesar_referencias(self, referencias: List[str], carpeta: Path) -> List[ParcelaData]:
        """
        Procesa cada referencia catastral: descarga XML y PDF, extrae geometría.
        
        Args:
            referencias: Lista de referencias catastrales
            carpeta: Carpeta donde guardar los archivos descargados
            
        Returns:
            Lista de ParcelaData con geometría válida
        """
        parcelas: List[ParcelaData] = []
        
        for i, rc in enumerate(referencias, 1):
            self.log(f"📍 [{i}/{len(referencias)}] Procesando {rc}...")
            
            parcela = ParcelaData(rc)
            xml_path = carpeta / f"{rc}_INSPIRE.xml"
            pdf_path = carpeta / f"{rc}_CDyG.pdf"

            # Descargar archivos
            self._descargar_xml(rc, xml_path)
            self._descargar_pdf(rc, pdf_path)

            # Extraer geometría del XML
            if xml_path.exists():
                superficie, coords = self._extraer_geometria(xml_path)
                if coords:
                    parcela.actualizar_geometria(coords, superficie)
                    
                    # Notificar geometría encontrada al frontend
                    if self.geometry_callback:
                        self.geometry_callback(parcela.refcat, coords, parcela.info_catastral)
                        
                    parcela.rutas.update({
                        "xml": str(xml_path),
                        "pdf": str(pdf_path),
                    })
                    parcelas.append(parcela)
                    self.log(f"   ✅ Geometría obtenida: {superficie:,.0f} m²")
                else:
                    self.log(f"   ⚠️ Referencia {rc} no contiene geometría válida en el XML.")
            else:
                self.log(f"   ❌ XML no disponible para la referencia {rc}.")
                
        return parcelas
    
    def _descargar_xml(self, rc: str, destino: Path) -> None:
        """
        Descarga el archivo XML INSPIRE desde el servicio WFS de Catastro.
        
        Args:
            rc: Referencia catastral
            destino: Ruta donde guardar el XML
        """
        url = (
            "https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx?service=WFS&version=2.0.0"
            f"&request=GetFeature&STOREDQUERY_ID=GetParcel&refcat={rc}"
        )
        
        try:
            respuesta = self.session.get(url, timeout=20)
            respuesta.raise_for_status()
            
            # Verificar que la respuesta es XML y no HTML (error del servidor)
            content_type = respuesta.headers.get('Content-Type', '').lower()
            contenido = respuesta.content.decode('utf-8', errors='ignore')
            
            # Detectar si es HTML (página de error o mantenimiento)
            if 'text/html' in content_type or contenido.strip().startswith('<HTML>') or contenido.strip().startswith('<!DOCTYPE'):
                # Buscar mensajes específicos de mantenimiento
                if 'MANTENIMIENTO' in contenido.upper() or 'MAINTENANCE' in contenido.upper():
                    self.log(f"⚠️ Servicio de Catastro en MANTENIMIENTO - no se pudo descargar XML para {rc}")
                    self.log(f"   Por favor, intente más tarde cuando el servicio esté disponible")
                else:
                    self.log(f"❌ El servidor devolvió HTML en lugar de XML para {rc}")
                    self.log(f"   Posible error en la referencia catastral o problema del servidor")
                return
            
            # Verificar que contiene datos XML válidos
            if not contenido.strip().startswith('<?xml'):
                self.log(f"⚠️ La respuesta no parece ser XML válido para {rc}")
                return
                
            destino.write_bytes(respuesta.content)
            
        except requests.RequestException as exc:
            self.log(f"❌ Error de conexión descargando XML para {rc}: {exc}")
    
    def _descargar_pdf(self, rc: str, destino: Path) -> None:
        """
        Descarga el PDF de Croquis y Datos Gráficos desde Catastro.
        
        Args:
            rc: Referencia catastral
            destino: Ruta donde guardar el PDF
        """
        # Evitar descargas duplicadas
        if destino.exists():
            return
            
        # URL del servicio que funciona correctamente
        url = (
            "https://www1.sedecatastro.gob.es/CYCBienInmueble/SECImprimirCroquisYDatos.aspx"
            f"?del={rc[:2]}&mun={rc[2:5]}&refcat={rc}"
        )
        
        try:
            respuesta = self.session.get(url, timeout=20)
            respuesta.raise_for_status()
            
            # Verificar que la respuesta es PDF y no HTML
            content_type = respuesta.headers.get('Content-Type', '').lower()
            
            # Si es HTML, probablemente hay un error
            if 'text/html' in content_type:
                contenido = respuesta.content.decode('utf-8', errors='ignore')
                if 'MANTENIMIENTO' in contenido.upper() or 'MAINTENANCE' in contenido.upper():
                    self.log(f"⚠️ Servicio de Catastro en MANTENIMIENTO - no se pudo descargar PDF para {rc}")
                else:
                    self.log(f"⚠️ No se pudo descargar el PDF para {rc} (servidor devolvió HTML)")
                return
            
            # Validación adicional por tamaño (PDFs válidos suelen ser > 8KB)
            if len(respuesta.content) > 8000:
                destino.write_bytes(respuesta.content)
            else:
                self.log(f"⚠️ PDF descargado para {rc} parece incompleto (tamaño: {len(respuesta.content)} bytes)")
            
        except requests.RequestException as exc:
            self.log(f"❌ Error de conexión descargando PDF para {rc}: {exc}")
    def _extraer_geometria(self, ruta_xml: Path) -> Tuple[float, List[Tuple[float, float]]]:
        """
        Extrae la superficie y las coordenadas del polígono desde el XML INSPIRE.
        
        Args:
            ruta_xml: Ruta al archivo XML
            
        Returns:
            Tupla (superficie_m2, lista_coordenadas)
            lista_coordenadas es una lista de tuplas (longitud, latitud)
        """
        superficie = 0.0
        coords: List[Tuple[float, float]] = []
        
        try:
            tree = ET.parse(str(ruta_xml))
            root = tree.getroot()
            
            # Namespaces del XML INSPIRE
            ns = {
                "cp": "http://inspire.ec.europa.eu/schemas/cp/4.0",
                "gml": "http://www.opengis.net/gml/3.2"
            }
            
            # Extraer superficie
            area_node = root.find(".//cp:areaValue", ns)
            if area_node is not None:
                superficie = float(area_node.text)
            
            # Extraer coordenadas (vienen como: lat1 lon1 lat2 lon2 ...)
            pos_list = root.find(".//gml:posList", ns)
            if pos_list is not None and pos_list.text:
                raw = pos_list.text.split()
                for i in range(0, len(raw), 2):
                    lat = float(raw[i])
                    lon = float(raw[i + 1])
                    coords.append((lon, lat))  # Guardamos como (lon, lat)
                    
        except ET.ParseError as exc:
            self.log(f"❌ XML corrupto o inválido en {ruta_xml.name}")
            self.log(f"   Causa probable: El servidor devolvió HTML en lugar de XML (mantenimiento o error)")
            self.log(f"   Detalle técnico: {exc}")
        except (ValueError, IndexError) as exc:
            self.log(f"⚠️ Lista de coordenadas incompleta en {ruta_xml.name}")
            self.log(f"   Detalle: {exc}")
            
        return superficie, coords

    # ═══════════════════════════════════════════════════════════════════════
    # PASO 4: GENERACIÓN DE KML
    # ═══════════════════════════════════════════════════════════════════════
    
    def _generar_kml(self, carpeta: Path, parcelas: List[ParcelaData]) -> None:
        """
        Genera archivos KML individuales para cada parcela y un KML maestro.
        
        Archivos generados:
        - [RC].kml: KML individual de cada parcela
        - MAPA_MAESTRO_TOTAL.kml: KML con todas las parcelas juntas
        
        Args:
            carpeta: Carpeta donde guardar los KML
            parcelas: Lista de parcelas a procesar
        """
        elementos: List[str] = []
        
        for parcela in parcelas:
            if not parcela.has_geometry():
                continue
                
            # Crear Placemark KML para esta parcela
            bloque = self._crear_placemark(parcela)
            elementos.append(bloque)
            
            # Guardar KML individual
            archivo_kml = carpeta / f"{parcela.refcat}.kml"
            archivo_kml.write_text(self._envoltorio_kml(bloque), encoding="utf-8")
            parcela.rutas["kml"] = str(archivo_kml)
        
        if elementos:
            maestro = carpeta / "MAPA_MAESTRO_TOTAL.kml"
            maestro.write_text(self._envoltorio_kml("".join(elementos)), encoding="utf-8")
            self.log(f"🗺️  KML maestro generado: {maestro.name}")

    @staticmethod
    def _crear_placemark(parcela: ParcelaData) -> str:
        """
        Crea un elemento Placemark KML para una parcela.
        
        Args:
            parcela: Datos de la parcela
            
        Returns:
            String XML con el Placemark
        """
        # Convertir coordenadas al formato KML: lon,lat,alt
        coords = " ".join(f"{lon},{lat},0" for lon, lat in parcela.geometria)
        
        return (
            f"<Placemark>"
            f"<name>{parcela.refcat}</name>"
            f"<description>m²: {parcela.info_catastral.get('m2', 0):,.0f}</description>"
            "<Style>"
            "<LineStyle><color>ff00ff00</color><width>2</width></LineStyle>"
            "<PolyStyle><color>4d00ff00</color></PolyStyle>"
            "</Style>"
            f"<Polygon><outerBoundaryIs><LinearRing>"
            f"<coordinates>{coords}</coordinates>"
            "</LinearRing></outerBoundaryIs></Polygon>"
            "</Placemark>"
        )

    @staticmethod
    def _envoltorio_kml(contenido: str) -> str:
        """
        Envuelve el contenido en la estructura XML de un archivo KML válido.
        
        Args:
            contenido: Contenido (uno o más Placemarks)
            
        Returns:
            String con el KML completo
        """
        return (
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<kml xmlns=\"http://www.opengis.net/kml/2.2\">\n"
            "<Document>\n"
            f"{contenido}\n"
            "</Document>\n"
            "</kml>"
        )

    # ═══════════════════════════════════════════════════════════════════════
    # PASO 5: GENERACIÓN DE PNG (SILUETAS)
    # ═══════════════════════════════════════════════════════════════════════
    
    def _generar_png(self, carpeta: Path, parcelas: List[ParcelaData]) -> None:
        """
        Genera siluetas PNG de las parcelas (individuales y conjunto).
        
        Archivos generados:
        - [RC]_silueta.png: Silueta individual de cada parcela
        - CONJUNTO_TOTAL.png: Todas las siluetas juntas
        
        Args:
            carpeta: Carpeta donde guardar los PNG
            parcelas: Lista de parcelas a dibujar
        """
        siluetas = []
        
        for parcela in parcelas:
            if not parcela.has_geometry():
                continue
                
            # Generar silueta individual
            ruta = carpeta / f"{parcela.refcat}_silueta.png"
            self._dibujar_parcelas([parcela.geometria], ruta, title=parcela.refcat)
            parcela.rutas["png"] = str(ruta)
            siluetas.append(parcela.geometria)
        
        # Generar silueta conjunta
        if siluetas:
            conjunto = carpeta / "CONJUNTO_TOTAL.png"
            self._dibujar_parcelas(siluetas, conjunto, title="Conjunto total", color="blue")
            self.log(f"🖼️  PNG conjunto generado: {conjunto.name}")

    @staticmethod
    def _dibujar_parcelas(
        lista_parcelas: List[List[Tuple[float, float]]],
        destino: Path,
        *,
        color: str = "red",
        title: str = ""
    ) -> None:
        """
        Dibuja una o más parcelas como siluetas PNG.
        
        Args:
            lista_parcelas: Lista de geometrías (cada una es una lista de coordenadas)
            destino: Ruta donde guardar el PNG
            color: Color de relleno y borde
            title: Título del gráfico
        """
        if not lista_parcelas:
            return
            
        fig, ax = plt.subplots(figsize=(6, 6))
        
        for coords in lista_parcelas:
            x, y = zip(*coords)
            ax.fill(x, y, color=color, alpha=0.3)
            ax.plot(x, y, color=color, linewidth=2)
        
        ax.axis("off")
        ax.set_aspect("equal", adjustable="box")
        
        if title:
            ax.set_title(title)
        
        fig.savefig(destino, transparent=True, bbox_inches="tight", pad_inches=0)
        plt.close(fig)

    # ═══════════════════════════════════════════════════════════════════════
    # PASO 6: CREAR TABLAS EXCEL/CSV
    # ═══════════════════════════════════════════════════════════════════════
    
    def _crear_tablas(self, carpeta: Path, parcelas: List[ParcelaData]) -> None:
        """
        Crea tablas Excel y CSV con los datos catastrales de las parcelas.
        
        Campos: Referencia, Polígono, Parcela, m2, Ha, Latitud, Longitud
        
        Archivos generados:
        - DATOS_CATASTRALES.xlsx
        - DATOS_CATASTRALES.csv (separador ;)
        
        Args:
            carpeta: Carpeta donde guardar las tablas
            parcelas: Lista de parcelas con datos
        """
        filas = [p.registro_tabla() for p in parcelas if p.info_catastral]
        
        if not filas:
            self.log("⚠️  No hay registros catastrales para exportar.")
            return
        
        df = pd.DataFrame(filas)
        excel = carpeta / "DATOS_CATASTRALES.xlsx"
        csv_path = carpeta / "DATOS_CATASTRALES.csv"
        
        df.to_excel(excel, index=False)
        df.to_csv(csv_path, sep=";", encoding="utf-8-sig", index=False)
        
        self.log(f"📊 Tablas generadas: {excel.name} / {csv_path.name}")

    # ═══════════════════════════════════════════════════════════════════════
    # PASO 7: GENERAR LOG DE EXPEDIENTE
    # ═══════════════════════════════════════════════════════════════════════
    
    def _generar_log_expediente(self, carpeta: Path, parcelas: List[ParcelaData]) -> None:
        """
        Genera archivo log.txt con resumen del expediente.
        
        Contenido:
        - Nombre del expediente
        - Fecha de proceso
        - Listado de referencias con superficies
        - Totales
        
        Args:
            carpeta: Carpeta donde guardar el log
            parcelas: Lista de parcelas procesadas
        """
        log_path = carpeta / "log.txt"
        
        with log_path.open("w", encoding="utf-8") as f:
            f.write(f"RESUMEN DE EXPEDIENTE: {carpeta.name}\n")
            f.write(f"FECHA DE PROCESO: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
            f.write("-" * 50 + "\n\n")
            
            total_m2 = 0
            for parcela in parcelas:
                m2 = parcela.info_catastral.get("m2", 0)
                total_m2 += m2
                f.write(f"RC: {parcela.refcat} | Superficie: {m2:,.0f} m2 | ({m2/10000:.4f} Ha)\n")
            
            f.write("\n" + "-" * 50 + "\n")
            f.write(f"TOTAL PARCELAS: {len(parcelas)}\n")
            f.write(f"SUPERFICIE TOTAL: {total_m2:,.0f} m2 | ({total_m2/10000:.4f} Ha)\n")
        
        self.log(f"📝 Archivo log.txt generado con éxito.")

    # ═══════════════════════════════════════════════════════════════════════
    # PASO 8: ANÁLISIS DE AFECCIONES CON CAPAS LOCALES
    # ═══════════════════════════════════════════════════════════════════════
    
    def _procesar_afecciones(self, carpeta: Path) -> None:
        """
        Analiza intersecciones usando archivos geoespaciales locales.
        
        Busca automáticamente capas en formato GPKG, SHP, GeoJSON, etc.
        en una carpeta especificada y calcula afecciones con la parcela.
        
        Args:
            carpeta: Carpeta donde guardar los resultados
        """
        archivo_parcela = carpeta / "MAPA_MAESTRO_TOTAL.kml"
        
        # Carpeta donde están las capas de afecciones
        carpeta_capas = self.carpeta_afecciones
        
        if not archivo_parcela.exists():
            self.log(f"⚠️  Falta {archivo_parcela.name} para definir zona de búsqueda.")
            return
        
        if not carpeta_capas.exists():
            self.log(f"⚠️  Falta la carpeta de capas: {carpeta_capas}")
            self.log(f"   Crea la carpeta y coloca allí tus archivos .gpkg, .shp, .geojson, etc.")
            return

        resultados = []

        try:
            # 1. Cargar Geometría de la Parcela (AOI)
            self.log(f"📍 Cargando parcela desde {archivo_parcela.name}...")
            parcela_gdf = gpd.read_file(str(archivo_parcela), driver='KML')
            if parcela_gdf.crs is None:
                parcela_gdf.crs = "EPSG:4326"
            
            # Proyectar a UTM 30N (Estándar para España Peninsular)
            parcela_utm = parcela_gdf.to_crs(epsg=25830)
            area_total_m2 = parcela_utm.area.sum()
            
            self.log(f"   ✓ Área total de la parcela: {area_total_m2/10000:.4f} ha")

            # ═══════════════════════════════════════════════════════════════
            # BUSCAR AUTOMÁTICAMENTE ARCHIVOS GEOESPACIALES
            # ═══════════════════════════════════════════════════════════════
            extensiones = ['.gpkg', '.shp', '.geojson', '.json', '.kml', '.kmz', '.gml']
            archivos_capa = []
            
            for ext in extensiones:
                archivos_capa.extend(carpeta_capas.glob(f"*{ext}"))
                archivos_capa.extend(carpeta_capas.glob(f"**/*{ext}"))  # Buscar en subcarpetas
            
            # Eliminar duplicados y ordenar
            archivos_capa = sorted(list(set(archivos_capa)))
            
            if not archivos_capa:
                self.log(f"❌ No se encontraron capas geoespaciales en {carpeta_capas}")
                self.log(f"   Extensiones buscadas: {', '.join(extensiones)}")
                return
            
            self.log(f"\n🗂️  Encontradas {len(archivos_capa)} capas para analizar:")
            for arch in archivos_capa:
                self.log(f"   • {arch.name}")

            # ═══════════════════════════════════════════════════════════════
            # PROCESAR CADA CAPA
            # ═══════════════════════════════════════════════════════════════
            self.log(f"\n🌍 Iniciando análisis de afecciones con capas locales...")

            for idx, archivo_capa in enumerate(archivos_capa, 1):
                nombre_capa = archivo_capa.stem
                self.log(f"\n[{idx}/{len(archivos_capa)}] 📡 Analizando: {nombre_capa}")
                
                try:
                    # Configurar GDAL para restaurar archivos .shx faltantes automáticamente
                    import os
                    os.environ['SHAPE_RESTORE_SHX'] = 'YES'
                    
                    # Cargar capa
                    capa_gdf = gpd.read_file(str(archivo_capa))
                    
                    if capa_gdf.empty:
                        self.log(f"   ⚪ Capa vacía: {nombre_capa}")
                        continue
                    
                    # Asegurar proyección correcta
                    if capa_gdf.crs is None:
                        self.log(f"   ⚠️  Sin CRS, asumiendo EPSG:25830")
                        capa_gdf.set_crs(epsg=25830, inplace=True)
                    else:
                        capa_gdf = capa_gdf.to_crs(epsg=25830)
                    
                    self.log(f"   ↪ Geometrías cargadas: {len(capa_gdf)}")

                    # CALCULAR INTERSECCIÓN
                    interseccion = gpd.overlay(
                        parcela_utm, 
                        capa_gdf, 
                        how='intersection', 
                        keep_geom_type=False
                    )
                    
                    if interseccion.empty:
                        self.log(f"   ⚪ Sin intersección con {nombre_capa}")
                        continue

                    area_afectada = interseccion.area.sum()
                    porcentaje = (area_afectada / area_total_m2) * 100

                    # Si el porcentaje es despreciable, ignorar
                    if porcentaje < 0.01:
                        self.log(f"   ⚪ Afección despreciable (<0.01%) en {nombre_capa}")
                        continue

                    # ═══════════════════════════════════════════════════════════
                    # ANÁLISIS DE ATRIBUTOS (detectar columnas relevantes)
                    # ═══════════════════════════════════════════════════════════
                    detalles = []
                    
                    # Buscar columnas que puedan contener información útil
                    columnas_interes = [
                        'nombre', 'name', 'tipo', 'type', 'uso', 'uso_sigpac', 
                        'categoria', 'codigo', 'code', 'zona', 'descripcion',
                        'clase', 'class', 'espacio', 'figura'
                    ]
                    
                    columna_encontrada = None
                    for col_buscar in columnas_interes:
                        # Buscar coincidencia case-insensitive
                        for col_real in interseccion.columns:
                            if col_buscar.lower() == col_real.lower():
                                columna_encontrada = col_real
                                break
                        if columna_encontrada:
                            break
                    
                    if columna_encontrada and columna_encontrada in interseccion.columns:
                        # Agrupar por tipo
                        grupos = interseccion.groupby(columna_encontrada).apply(
                            lambda x: x.area.sum()
                        )
                        for etiqueta, sup in grupos.items():
                            detalles.append(f"{etiqueta}: {sup/10000:.4f} ha")
                        
                        detalle_texto = " | ".join(detalles[:5])  # Limitar a 5 para legibilidad
                    else:
                        detalle_texto = f"{len(interseccion)} geometría(s) afectada(s)"

                    # Guardar resultado
                    resultados.append({
                        'capa': nombre_capa,
                        'archivo': archivo_capa.name,
                        'afecta': 'SÍ',
                        'superficie_ha': round(area_afectada / 10000, 4),
                        'porcentaje': round(porcentaje, 2),
                        'detalle': detalle_texto,
                        'geometrias': len(interseccion)
                    })

                    # ═══════════════════════════════════════════════════════════
                    # GENERAR MAPA DE EVIDENCIA
                    # ═══════════════════════════════════════════════════════════
                    fig, ax = plt.subplots(figsize=(12, 10))
                    
                    # 1. Capa completa (contexto en gris claro)
                    try:
                        capa_gdf.to_crs(epsg=3857).plot(
                            ax=ax, 
                            color='lightgray', 
                            alpha=0.3, 
                            edgecolor='gray',
                            linewidth=0.5,
                            zorder=1,
                            label='Capa completa'
                        )
                    except:
                        pass
                    
                    # 2. Intersección (zona afectada en rojo)
                    interseccion.to_crs(epsg=3857).plot(
                        ax=ax, 
                        color='red', 
                        alpha=0.6, 
                        edgecolor='darkred',
                        linewidth=1.5,
                        zorder=5,
                        label='Zona afectada'
                    )
                    
                    # 3. Parcela (borde azul)
                    parcela_utm.to_crs(epsg=3857).plot(
                        ax=ax, 
                        facecolor="none", 
                        edgecolor="blue", 
                        linewidth=3,
                        zorder=10,
                        label="Parcela"
                    )
                    
                    # 4. Mapa Base
                    try:
                        cx.add_basemap(ax, source=cx.providers.OpenStreetMap.Mapnik, zoom='auto')
                    except:
                        pass  # Si falla internet, mapa sin fondo
                    
                    ax.set_axis_off()
                    ax.legend(loc='upper right', fontsize=10)
                    ax.set_title(
                        f"{nombre_capa}\n"
                        f"Afección: {porcentaje:.2f}% ({area_afectada/10000:.4f} ha)\n"
                        f"{detalle_texto[:100]}",  # Limitar longitud
                        fontsize=11,
                        pad=20
                    )
                    
                    # Guardar mapa
                    nombre_mapa = f"mapa_afeccion_{idx:02d}_{nombre_capa[:30]}.png"
                    ruta_mapa = carpeta / nombre_mapa
                    plt.savefig(ruta_mapa, dpi=150, bbox_inches='tight')
                    plt.close()
                    
                    self.log(f"   ✅ AFECCIÓN DETECTADA: {porcentaje:.2f}%")
                    self.log(f"      ↪ {detalle_texto[:80]}")
                    self.log(f"      ↪ Mapa guardado: {nombre_mapa}")

                except Exception as e:
                    self.log(f"   ❌ Error procesando {nombre_capa}: {str(e)}")
                    import traceback
                    self.log(f"      {traceback.format_exc()}")

            # ═══════════════════════════════════════════════════════════════
            # EXPORTAR INFORME FINAL
            # ═══════════════════════════════════════════════════════════════
            if resultados:
                df = pd.DataFrame(resultados)
                
                # Ordenar por porcentaje de afección (mayor a menor)
                df = df.sort_values('porcentaje', ascending=False)
                
                csv_path = carpeta / "afecciones_analisis.csv"
                excel_path = carpeta / "afecciones_analisis.xlsx"
                
                df.to_csv(csv_path, index=False, sep=";", encoding='utf-8-sig')
                df.to_excel(excel_path, index=False, engine='openpyxl')
                
                self.log(f"\n📄 ═══════════════════════════════════════")
                self.log(f"   INFORME DE AFECCIONES GENERADO")
                self.log(f"   ═══════════════════════════════════════")
                self.log(f"   📊 Total capas con afección: {len(resultados)}")
                self.log(f"   📁 Excel: {excel_path.name}")
                self.log(f"   📁 CSV: {csv_path.name}")
                self.log(f"   🗺️  Mapas generados: {len(resultados)}")
                
                # Resumen en consola
                self.log(f"\n{'='*60}")
                self.log(f"RESUMEN DE AFECCIONES DETECTADAS")
                self.log(f"{'='*60}")
                for _, fila in df.iterrows():
                    self.log(f"• {fila['capa']}: {fila['porcentaje']}% ({fila['superficie_ha']} ha)")
                self.log(f"{'='*60}\n")
                
            else:
                self.log("\n✅ Análisis completado: No se detectaron afecciones relevantes.")

        except Exception as e:
            self.log(f"\n❌ Error crítico en módulo de afecciones: {e}")
            import traceback
            self.log(traceback.format_exc())

    # ═══════════════════════════════════════════════════════════════════════
    # PASO 9: PLANO DE EMPLAZAMIENTO (MAPA BASE)
    # ═══════════════════════════════════════════════════════════════════════
    
    def _generar_plano_emplazamiento(self, carpeta: Path) -> None:
        """
        Genera plano de emplazamiento sobre mapa base OpenStreetMap.
        
        Características:
        - Formato 4:3 (12x9 pulgadas)
        - 300 DPI (alta resolución)
        - Margen 1.8x alrededor de las parcelas
        - Parcelas en rojo semi-transparente
        
        Archivo generado: PLANO-EMPLAZAMIENTO.jpg
        
        Args:
            carpeta: Carpeta donde guardar el plano
        """
        ruta_kml = carpeta / "MAPA_MAESTRO_TOTAL.kml"
        if not ruta_kml.exists():
            self.log(f"⚠️  No se encontró {ruta_kml.name}")
            return

        try:
            # Cargar KML
            gdf = gpd.read_file(str(ruta_kml), driver='KML')
            if gdf.empty:
                return
            if gdf.crs is None:
                gdf.crs = "EPSG:4326"
            
            # Configurar figura en formato 4:3
            fig, ax = plt.subplots(figsize=(12, 9))
            
            # Calcular límites con margen
            minx, miny, maxx, maxy = gdf.total_bounds
            centro_x, centro_y = (minx + maxx) / 2, (miny + maxy) / 2
            
            ancho_parcelas = (maxx - minx) * 1.8  # Margen 1.8x
            alto_parcelas = (maxy - miny) * 1.8
            
            # Ajustar para mantener proporción 4:3
            if ancho_parcelas / alto_parcelas > 4/3:
                alto_final = ancho_parcelas * (3/4)
                ancho_final = ancho_parcelas
            else:
                ancho_final = alto_parcelas * (4/3)
                alto_final = alto_parcelas
                
            ax.set_xlim(centro_x - ancho_final/2, centro_x + ancho_final/2)
            ax.set_ylim(centro_y - alto_final/2, centro_y + alto_final/2)

            # Dibujar parcelas en rojo
            gdf.plot(ax=ax, facecolor='red', alpha=0.3, edgecolor='darkred', linewidth=1.5, zorder=2)
            
            # Añadir mapa base OpenStreetMap
            cx.add_basemap(ax, crs=gdf.crs.to_string(), source=cx.providers.OpenStreetMap.Mapnik, zorder=1)
            
            ax.set_axis_off()
            
            ruta_jpg = carpeta / "PLANO-EMPLAZAMIENTO.jpg"
            plt.savefig(ruta_jpg, dpi=300, bbox_inches='tight', pad_inches=0)
            plt.close()
            self.log(f"✅ PLANO-EMPLAZAMIENTO.jpg generado (300 DPI)")
            
        except Exception as e:
            self.log(f"❌ Error al generar el plano: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # PASO 10: PLANO DE EMPLAZAMIENTO (ORTOFOTO)
    # ═══════════════════════════════════════════════════════════════════════
    
    def _generar_plano_ortofoto(self, carpeta: Path) -> None:
        """
        Genera plano de emplazamiento sobre ortofoto satelital Esri.
        
        Características:
        - Formato 4:3 (12x9 pulgadas)
        - 300 DPI (alta resolución)
        - Margen 1.8x alrededor de las parcelas
        - Parcelas en cian (resalta sobre la imagen)
        - Fondo: Esri WorldImagery
        
        Archivo generado: PLANO-EMPLAZAMIENTO-ORTO.jpg
        
        Args:
            carpeta: Carpeta donde guardar el plano
        """
        ruta_kml = carpeta / "MAPA_MAESTRO_TOTAL.kml"
        if not ruta_kml.exists():
            self.log(f"⚠️  No se encontró {ruta_kml.name}")
            return

        try:
            # Cargar KML
            gdf = gpd.read_file(str(ruta_kml), driver='KML')
            if gdf.empty:
                return
            if gdf.crs is None:
                gdf.crs = "EPSG:4326"
            
            # Configurar figura en formato 4:3
            fig, ax = plt.subplots(figsize=(12, 9))
            
            # Calcular límites con margen
            minx, miny, maxx, maxy = gdf.total_bounds
            centro_x, centro_y = (minx + maxx) / 2, (miny + maxy) / 2
            
            ancho_parcelas = (maxx - minx) * 1.8
            alto_parcelas = (maxy - miny) * 1.8
            
            # Ajustar para mantener proporción 4:3
            if ancho_parcelas / alto_parcelas > 4/3:
                alto_final = ancho_parcelas * (3/4)
                ancho_final = ancho_parcelas
            else:
                ancho_final = alto_parcelas * (4/3)
                alto_final = alto_parcelas
                
            ax.set_xlim(centro_x - ancho_final/2, centro_x + ancho_final/2)
            ax.set_ylim(centro_y - alto_final/2, centro_y + alto_final/2)

            # Dibujar parcelas en cian (solo borde, sin relleno)
            gdf.plot(ax=ax, facecolor='none', edgecolor='cyan', linewidth=2.5, zorder=2)
            
            # Añadir ortofoto Esri WorldImagery
            cx.add_basemap(ax, crs=gdf.crs.to_string(), source=cx.providers.Esri.WorldImagery, zorder=1)
            
            ax.set_axis_off()
            
            ruta_jpg = carpeta / "PLANO-EMPLAZAMIENTO-ORTO.jpg"
            plt.savefig(ruta_jpg, dpi=300, bbox_inches='tight', pad_inches=0)
            plt.close()
            self.log(f"✅ PLANO-EMPLAZAMIENTO-ORTO.jpg generado (300 DPI)")
            
        except Exception as e:
            self.log(f"❌ Error al generar la ortofoto: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # PASO 11: PLANO CATASTRAL (1000m)
    # ═══════════════════════════════════════════════════════════════════════
    
    def _generar_plano_catastral(self, carpeta: Path) -> None:
        """
        Genera plano catastral con encuadre fijo de 1000m usando WMS de Catastro.
        
        Características:
        - Encuadre cuadrado de 1000m x 1000m
        - Centrado en el centro geométrico de las parcelas
        - Proyección: EPSG:25830 (UTM 30N)
        - Parcelas en cian sobre la cartografía catastral
        
        Archivo generado: PLANO-CATASTRAL-map.jpg
        
        Args:
            carpeta: Carpeta donde guardar el plano
        """
        ruta_kml = carpeta / "MAPA_MAESTRO_TOTAL.kml"
        if not ruta_kml.exists():
            self.log(f"⚠️  No se encontró {ruta_kml.name}")
            return

        try:
            # Cargar y proyectar a UTM 30N
            gdf = gpd.read_file(str(ruta_kml), driver='KML').to_crs(epsg=25830)
            b = gdf.total_bounds
            
            # Calcular encuadre cuadrado de 1000m
            centro_x = (b[0] + b[2]) / 2
            centro_y = (b[1] + b[3]) / 2
            lado_cuadrado = 1000  # metros
            
            xmin = centro_x - (lado_cuadrado / 2)
            xmax = centro_x + (lado_cuadrado / 2)
            ymin = centro_y - (lado_cuadrado / 2)
            ymax = centro_y + (lado_cuadrado / 2)
            
            bbox_str = f"{xmin},{ymin},{xmax},{ymax}"
            
            self.log(f"🌍 Generando plano catastral (1000m)...")
            
            # Petición WMS al servidor de Catastro
            url = (
                f"https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx?"
                f"SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=CATASTRO"
                f"&SRS=EPSG:25830&BBOX={bbox_str}&WIDTH=1800&HEIGHT=1800&FORMAT=image/png"
            )
            
            r = self.session.get(url, timeout=30)
            if r.status_code == 200:
                img_mapa = Image.open(BytesIO(r.content))
                
                # Crear figura cuadrada
                fig = plt.figure(figsize=(10, 10))
                ax = fig.add_axes([0, 0, 1, 1])
                ax.imshow(img_mapa, extent=[xmin, xmax, ymin, ymax])
                
                # Dibujar parcelas en cian
                gdf.plot(ax=ax, facecolor='none', edgecolor='cyan', linewidth=1.5)
                
                ax.set_axis_off()
                ax.set_xlim(xmin, xmax)
                ax.set_ylim(ymin, ymax)
                
                # Guardar como JPEG
                buf = BytesIO()
                plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0)
                plt.close()
                buf.seek(0)
                final_img = Image.open(buf).convert('RGB')
                nombre_salida = carpeta / "PLANO-CATASTRAL-map.jpg"
                final_img.save(nombre_salida, "JPEG", quality=85, optimize=True)
                self.log(f"   ✅ Generado correctamente")
            else:
                self.log(f"   ❌ Error del servidor WMS")
        except Exception as e:
            self.log(f"❌ Error: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # PASO 12: PLANOS IGN (V1 y V2)
    # ═══════════════════════════════════════════════════════════════════════
    
    def _generar_planos_ign(self, carpeta: Path) -> None:
        """
        Genera planos IGN con zoom fijo 16 y dos variantes de encuadre.
        
        Variantes:
        - V1: Margen de 500m (vista cercana)
        - V2: Margen de 3000m (vista alejada, contexto)
        
        Características:
        - Formato 4:3 (12x9 pulgadas)
        - Zoom 16 fijo (máximo detalle de topónimos)
        - 150 DPI
        - Parcelas en cian
        - Fondo: Mapa Topográfico Nacional del IGN (WMTS)
        
        Archivos generados:
        - PLANO-IGN-V1.jpg
        - PLANO-IGN-V2.jpg
        
        Args:
            carpeta: Carpeta donde guardar los planos
        """
        ruta_kml = carpeta / "MAPA_MAESTRO_TOTAL.kml"
        if not ruta_kml.exists():
            self.log(f"⚠️  No se encontró {ruta_kml.name}")
            return

        try:
            # Cargar y proyectar a Web Mercator
            gdf = gpd.read_file(str(ruta_kml), driver='KML')
            if gdf.empty:
                return
            if gdf.crs is None:
                gdf.crs = "EPSG:4326"
            gdf_3857 = gdf.to_crs(epsg=3857)
            
            minx, miny, maxx, maxy = gdf_3857.total_bounds
            
            # URL del servicio WMTS del IGN
            ign_url = (
                "https://www.ign.es/wmts/mapa-raster?"
                "layer=MTN&style=default&tilematrixset=GoogleMapsCompatible"
                "&Service=WMTS&Request=GetTile&Version=1.0.0&Format=image/jpeg"
                "&TileMatrix={z}&TileCol={x}&TileRow={y}"
            )
            
            # Generar ambas variantes
            for margen, nombre in [(500, "PLANO-IGN-V1.jpg"), (3000, "PLANO-IGN-V2.jpg")]:
                self.log(f"🗺️  Generando {nombre} (margen {margen}m, zoom 16)...")
                
                fig, ax = plt.subplots(figsize=(12, 9))
                
                # Calcular límites con margen
                x_min, x_max = minx - margen, maxx + margen
                y_min, y_max = miny - margen, maxy + margen
                ancho, alto = x_max - x_min, y_max - y_min
                
                # Ajustar para mantener proporción 4:3
                if ancho / alto > 4/3:
                    alto_f = ancho * (3/4)
                    cy = (y_min + y_max) / 2
                    ax.set_ylim(cy - alto_f/2, cy + alto_f/2)
                    ax.set_xlim(x_min, x_max)
                else:
                    ancho_f = alto * (4/3)
                    cx_coord = (x_min + x_max) / 2
                    ax.set_xlim(cx_coord - ancho_f/2, cx_coord + ancho_f/2)
                    ax.set_ylim(y_min, y_max)
                
                # Añadir mapa IGN con zoom 16 fijo
                cx.add_basemap(ax, source=ign_url, zorder=1, zoom=16)
                
                # Dibujar parcelas en cian
                gdf_3857.plot(ax=ax, facecolor='none', edgecolor='cyan', linewidth=2, zorder=2)
                ax.set_axis_off()
                
                ruta_final = carpeta / nombre
                plt.savefig(ruta_final, dpi=150, bbox_inches='tight', pad_inches=0, pil_kwargs={'quality': 80})
                plt.close()
                self.log(f"   ✅ Generado correctamente")
        except Exception as e:
            self.log(f"❌ Error: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # PASO 13: PLANOS PROVINCIALES (3 variantes)
    # ═══════════════════════════════════════════════════════════════════════
    
    def _generar_planos_provinciales(self, carpeta: Path) -> None:
        """
        Genera planos de localización provincial con 3 estilos de mapa base.
        
        Variantes:
        - STREETS: ArcGIS World Street Map
        - TOPO: ArcGIS World Topo Map
        - OSM: OpenStreetMap Mapnik
        
        Características:
        - Encuadre de 100km (vista provincial completa)
        - Zoom 10 (óptimo para topónimos provinciales)
        - Formato 4:3 (12x9 pulgadas)
        - 120 DPI (suficiente para escala provincial)
        - Parcelas en cian con chincheta roja de ubicación
        
        Archivos generados:
        - PLANO-PROVINCIAL-V1-STREETS.jpg
        - PLANO-PROVINCIAL-V1-TOPO.jpg
        - PLANO-PROVINCIAL-V1-OSM.jpg
        
        Args:
            carpeta: Carpeta donde guardar los planos
        """
        ruta_kml = carpeta / "MAPA_MAESTRO_TOTAL.kml"
        if not ruta_kml.exists():
            self.log(f"⚠️  No se encontró {ruta_kml.name}")
            return

        try:
            # Cargar y proyectar
            gdf = gpd.read_file(str(ruta_kml), driver='KML')
            if gdf.empty:
                return
            gdf_3857 = gdf.to_crs(epsg=3857)
            minx, miny, maxx, maxy = gdf_3857.total_bounds
            centro_x, centro_y = (minx + maxx) / 2, (miny + maxy) / 2
            
            # Definir las 3 variantes de mapa base
            variantes = {
                "STREETS": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
                "TOPO": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
                "OSM": cx.providers.OpenStreetMap.Mapnik
            }
            
            for nombre, fuente in variantes.items():
                self.log(f"🗺️  Generando PLANO-PROVINCIAL-V1-{nombre}.jpg...")
                
                fig, ax = plt.subplots(figsize=(12, 9))
                
                # Encuadre de 100km
                ancho_vista = 100000  # metros
                alto_vista = ancho_vista * (3/4)  # Mantener 4:3
                
                ax.set_xlim(centro_x - ancho_vista/2, centro_x + ancho_vista/2)
                ax.set_ylim(centro_y - alto_vista/2, centro_y + alto_vista/2)
                
                # Añadir mapa base con zoom 10
                cx.add_basemap(ax, source=fuente, zoom=10, interpolation='lanczos', zorder=1)
                
                # Dibujar parcelas en cian (relleno y borde)
                gdf_3857.plot(ax=ax, color='cyan', edgecolor='cyan', linewidth=3, zorder=3)
                
                # Añadir chincheta roja en el centro
                ax.plot(centro_x, centro_y, marker='v', color='red', markersize=20, 
                        markeredgecolor='white', markeredgewidth=1.5, zorder=4)
                
                ax.set_axis_off()
                
                nombre_archivo = f"PLANO-PROVINCIAL-V1-{nombre}.jpg"
                ruta_final = carpeta / nombre_archivo
                plt.savefig(ruta_final, dpi=120, bbox_inches='tight', pad_inches=0, 
                           pil_kwargs={'quality': 85, 'optimize': True, 'progressive': True})
                plt.close()
                self.log(f"   ✅ Generado correctamente")
        except Exception as e:
            self.log(f"❌ Error provincial: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # PASO 14: PLANOS HISTÓRICOS (MTN25, MTN50, CATASTRONES)
    # ═══════════════════════════════════════════════════════════════════════
    
    def _generar_planos_historicos(self, carpeta: Path) -> None:
        """
        Genera planos con cartografía histórica del IGN.
        
        Capas:
        - MTN25: Mapa Topográfico Nacional 1:25.000 (primera edición)
        - MTN50: Mapa Topográfico Nacional 1:50.000 (primera edición)
        - CATASTRONES: Planos del Catastro histórico
        
        Características:
        - Encuadre de 5km alrededor de las parcelas
        - Formato 4:3 (12x9 pulgadas)
        - 150 DPI
        - Parcelas en cian con chincheta roja semi-transparente
        - Fuente: WMS del IGN (primera edición MTN)
        
        Archivos generados:
        - PLANO-MTN25.jpg
        - PLANO-MTN50.jpg
        - PLANO-CATASTRONES.jpg
        
        Args:
            carpeta: Carpeta donde guardar los planos
        """
        ruta_kml = carpeta / "MAPA_MAESTRO_TOTAL.kml"
        if not ruta_kml.exists():
            self.log(f"⚠️  No se encontró {ruta_kml.name}")
            return

        try:
            # Cargar y proyectar
            gdf = gpd.read_file(str(ruta_kml), driver='KML')
            if gdf.empty:
                return
            gdf_3857 = gdf.to_crs(epsg=3857)
            minx, miny, maxx, maxy = gdf_3857.total_bounds
            cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
            
            # Encuadre de 5km
            m = 5000
            bbox = [cx - m, cy - m * 0.75, cx + m, cy + m * 0.75]
            
            # Definir las 3 capas históricas
            capas = {
                "MTN25": "MTN25",
                "MTN50": "MTN50",
                "CATASTRONES": "catastrones"
            }
            
            url_wms = "https://www.ign.es/wms/primera-edicion-mtn"
            
            for nombre_file, id_capa in capas.items():
                self.log(f"🛰️  Capturando {nombre_file}...")
                
                # Parámetros de la petición WMS
                params = {
                    "SERVICE": "WMS",
                    "VERSION": "1.3.0",
                    "REQUEST": "GetMap",
                    "LAYERS": id_capa,
                    "STYLES": "",
                    "CRS": "EPSG:3857",
                    "BBOX": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
                    "WIDTH": "1200",
                    "HEIGHT": "900",
                    "FORMAT": "image/jpeg",
                    "TRANSPARENT": "FALSE"
                }
                
                try:
                    response = self.session.get(url_wms, params=params, timeout=30)
                    if response.status_code == 200 and 'image' in response.headers.get('Content-Type', ''):
                        img = Image.open(BytesIO(response.content))
                        
                        fig, ax = plt.subplots(figsize=(12, 9))
                        ax.imshow(img, extent=[bbox[0], bbox[2], bbox[1], bbox[3]], interpolation='lanczos')
                        
                        # Dibujar parcelas en cian
                        gdf_3857.plot(ax=ax, facecolor='none', edgecolor='cyan', linewidth=1.5, zorder=10)
                        
                        # Añadir chincheta roja semi-transparente
                        ax.plot(cx, cy, marker='v', color='red', markersize=18, 
                                markeredgecolor='white', markeredgewidth=1.5, alpha=0.5, zorder=11)
                        
                        ax.set_xlim(bbox[0], bbox[2])
                        ax.set_ylim(bbox[1], bbox[3])
                        ax.set_axis_off()
                        
                        nombre_archivo = f"PLANO-{nombre_file}.jpg"
                        ruta_final = carpeta / nombre_archivo
                        plt.savefig(ruta_final, dpi=150, bbox_inches='tight', pad_inches=0, pil_kwargs={'quality': 90})
                        plt.close()
                        self.log(f"   ✅ Generado correctamente")
                    else:
                        self.log(f"   ❌ Error del servidor")
                except Exception as e:
                    self.log(f"❌ Error: {e}")
        except Exception as e:
            self.log(f"❌ Error crítico: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # PASO 16: PLANO DE PENDIENTES CON LEYENDA
    # ═══════════════════════════════════════════════════════════════════════
    
    def _generar_plano_pendientes(self, carpeta: Path) -> None:
        """
        Genera plano de pendientes del terreno con leyenda superpuesta.
        
        Características:
        - Encuadre de 500m alrededor de las parcelas (vista cercana)
        - Formato 4:3 (12x9 pulgadas)
        - 150 DPI
        - Parcelas en azul (#0000FF)
        - Chincheta en rojo (#CC0000) con transparencia
        - Leyenda superpuesta en la esquina inferior derecha
        - Fuente: WMS de Pendientes IDEE (capa MDP05)
        
        Archivo generado: PLANO-PENDIENTES-LEYENDA.jpg
        
        Args:
            carpeta: Carpeta donde guardar el plano
        """
        ruta_kml = carpeta / "MAPA_MAESTRO_TOTAL.kml"
        if not ruta_kml.exists():
            self.log(f"⚠️  No se encontró {ruta_kml.name}")
            return

        try:
            # Cargar y proyectar
            gdf = gpd.read_file(str(ruta_kml), driver='KML')
            if gdf.empty:
                return
            gdf_3857 = gdf.to_crs(epsg=3857)
            minx, miny, maxx, maxy = gdf_3857.total_bounds
            cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
            
            # Encuadre cercano de 500m
            m = 500
            bbox = [cx - m, cy - m * 0.75, cx + m, cy + m * 0.75]
            
            url_wms = "https://wms-pendientes.idee.es/pendientes"
            
            # Parámetros para el mapa de pendientes
            params_mapa = {
                "SERVICE": "WMS",
                "VERSION": "1.1.1",
                "REQUEST": "GetMap",
                "LAYERS": "MDP05",
                "STYLES": "",
                "SRS": "EPSG:3857",
                "BBOX": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
                "WIDTH": "1500",
                "HEIGHT": "1125",
                "FORMAT": "image/png",
                "TRANSPARENT": "FALSE"
            }
            
            # Parámetros para la leyenda
            params_leyenda = {
                "SERVICE": "WMS",
                "VERSION": "1.1.1",
                "REQUEST": "GetLegendGraphic",
                "LAYER": "MDP05",
                "FORMAT": "image/png",
                "WIDTH": "200",
                "HEIGHT": "400"
            }
            
            self.log(f"🛰️  Capturando Pendientes y Leyenda...")
            
            response_mapa = self.session.get(url_wms, params=params_mapa, timeout=45)
            response_leyenda = self.session.get(url_wms, params=params_leyenda, timeout=45)
            
            if response_mapa.status_code == 200 and 'image' in response_mapa.headers.get('Content-Type', ''):
                img_mapa = Image.open(BytesIO(response_mapa.content))
                img_leyenda = None
                
                if response_leyenda.status_code == 200 and 'image' in response_leyenda.headers.get('Content-Type', ''):
                    img_leyenda = Image.open(BytesIO(response_leyenda.content))
                
                fig, ax = plt.subplots(figsize=(12, 9))
                ax.imshow(img_mapa, extent=[bbox[0], bbox[2], bbox[1], bbox[3]], interpolation='lanczos')
                
                # Dibujar parcelas en azul
                gdf_3857.plot(ax=ax, facecolor='none', edgecolor='#0000FF', linewidth=1.5, zorder=10)
                
                # Chincheta roja con transparencia
                ax.plot(cx, cy, marker='v', color='#CC0000', markersize=22, 
                        markeredgecolor='white', markeredgewidth=2.5, alpha=0.7, zorder=11)
                
                # Añadir leyenda si se descargó correctamente
                if img_leyenda:
                    ax_leg = fig.add_axes([0.75, 0.15, 0.15, 0.3])
                    ax_leg.imshow(img_leyenda)
                    ax_leg.axis('off')
                    ax_leg.patch.set_facecolor('white')
                    ax_leg.patch.set_alpha(0.8)
                
                ax.set_xlim(bbox[0], bbox[2])
                ax.set_ylim(bbox[1], bbox[3])
                ax.set_axis_off()
                
                ruta_final = carpeta / "PLANO-PENDIENTES-LEYENDA.jpg"
                plt.savefig(ruta_final, dpi=150, bbox_inches='tight', pad_inches=0)
                plt.close()
                self.log(f"   ✅ Generado correctamente")
        except Exception as e:
            self.log(f"❌ Error: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # PASO 17: PLANO RED NATURA 2000
    # ═══════════════════════════════════════════════════════════════════════
    
    def _generar_plano_natura2000(self, carpeta: Path) -> None:
        """
        Genera plano de Red Natura 2000 sobre ortofoto PNOA con leyenda.
        
        Características:
        - Encuadre de 5km (vista de contexto ambiental)
        - Formato 4:3 (12x9 pulgadas)
        - 150 DPI
        - Base: Ortofoto PNOA del IGN
        - Capa: Red Natura 2000 con transparencia 70%
        - Parcelas en azul (#0000FF)
        - Chincheta en rojo (#CC0000) con alta opacidad
        - Leyenda reducida en esquina inferior izquierda
        - Fuentes: WMS PNOA (IGN) + WMS Red Natura (MAPAMA)
        
        Archivo generado: PLANO-NATURA-2000.jpg
        
        Args:
            carpeta: Carpeta donde guardar el plano
        """
        ruta_kml = carpeta / "MAPA_MAESTRO_TOTAL.kml"
        if not ruta_kml.exists():
            self.log(f"⚠️  No se encontró {ruta_kml.name}")
            return

        try:
            # Cargar y proyectar
            gdf = gpd.read_file(str(ruta_kml), driver='KML')
            if gdf.empty:
                return
            gdf_3857 = gdf.to_crs(epsg=3857)
            minx, miny, maxx, maxy = gdf_3857.total_bounds
            cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
            
            # Encuadre de 5km
            m = 5000
            bbox = [cx - m, cy - m * 0.75, cx + m, cy + m * 0.75]
            
            url_pnoa = "https://www.ign.es/wms-inspire/pnoa-ma"
            url_natura = "https://wms.mapama.gob.es/sig/Biodiversidad/RedNatura/wms.aspx"
            capa_natura = "PS.ProtectedSite"
            
            # Parámetros para la ortofoto base
            params_base = {
                "SERVICE": "WMS",
                "VERSION": "1.1.1",
                "REQUEST": "GetMap",
                "LAYERS": "OI.OrthoimageCoverage",
                "STYLES": "",
                "SRS": "EPSG:3857",
                "BBOX": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
                "WIDTH": "1500",
                "HEIGHT": "1125",
                "FORMAT": "image/jpeg"
            }
            
            # Parámetros para la capa de Red Natura
            params_natura = {
                "SERVICE": "WMS",
                "VERSION": "1.1.1",
                "REQUEST": "GetMap",
                "LAYERS": capa_natura,
                "STYLES": "",
                "SRS": "EPSG:3857",
                "BBOX": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
                "WIDTH": "1500",
                "HEIGHT": "1125",
                "FORMAT": "image/png",
                "TRANSPARENT": "TRUE"
            }
            
            # Parámetros para la leyenda
            params_leyenda = {
                "SERVICE": "WMS",
                "VERSION": "1.1.1",
                "REQUEST": "GetLegendGraphic",
                "LAYER": capa_natura,
                "FORMAT": "image/png"
            }
            
            self.log(f"🛰️  Generando Plano Natura 2000...")
            
            response_base = self.session.get(url_pnoa, params=params_base, timeout=45)
            response_natura = self.session.get(url_natura, params=params_natura, timeout=45)
            response_leyenda = self.session.get(url_natura, params=params_leyenda, timeout=45)
            
            if (response_base.status_code == 200 and response_natura.status_code == 200 and
                'image' in response_base.headers.get('Content-Type', '') and
                'image' in response_natura.headers.get('Content-Type', '')):
                
                img_base = Image.open(BytesIO(response_base.content))
                img_natura = Image.open(BytesIO(response_natura.content))
                img_leyenda = None
                
                if response_leyenda.status_code == 200 and 'image' in response_leyenda.headers.get('Content-Type', ''):
                    img_leyenda = Image.open(BytesIO(response_leyenda.content))
                
                # Crear figura sin márgenes
                fig = plt.figure(figsize=(12, 9))
                ax = fig.add_axes([0, 0, 1, 1])
                
                # Capa base: ortofoto PNOA
                ax.imshow(img_base, extent=[bbox[0], bbox[2], bbox[1], bbox[3]])
                
                # Capa de Red Natura 2000 con transparencia 70%
                ax.imshow(img_natura, extent=[bbox[0], bbox[2], bbox[1], bbox[3]], alpha=0.7)
                
                # Dibujar parcelas en azul
                gdf_3857.plot(ax=ax, facecolor='none', edgecolor='#0000FF', linewidth=1.5, zorder=10)
                
                # Chincheta roja con alta opacidad
                ax.plot(cx, cy, marker='v', color='#CC0000', markersize=22,
                        markeredgecolor='white', markeredgewidth=2.5, alpha=0.9, zorder=11)
                
                # Añadir leyenda reducida en esquina inferior izquierda
                if img_leyenda:
                    ax_leg = fig.add_axes([0.01, 0.01, 0.10, 0.12])
                    ax_leg.imshow(img_leyenda, aspect='equal')
                    ax_leg.axis('off')
                
                ax.set_xlim(bbox[0], bbox[2])
                ax.set_ylim(bbox[1], bbox[3])
                ax.set_axis_off()
                
                ruta_final = carpeta / "PLANO-NATURA-2000.jpg"
                plt.savefig(ruta_final, dpi=150, bbox_inches=None, pad_inches=0, pil_kwargs={'quality': 95})
                plt.close()
                self.log(f"   ✅ Generado correctamente")
        except Exception as e:
            self.log(f"❌ Error: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # PASO 18: PLANO MONTES PÚBLICOS (CMUP) 🆕
    # ═══════════════════════════════════════════════════════════════════════

    def _descargar_imagen_wms(self, url: str, params: dict) -> Optional[Image.Image]:
        """
        Descarga una imagen desde un servicio WMS.
        
        Args:
            url: URL del servicio WMS
            params: Parámetros de la petición
            
        Returns:
            Imagen PIL o None si hay error
        """
        try:
            response = self.session.get(url, params=params, timeout=60)
            if response.status_code == 200 and 'image' in response.headers.get('Content-Type', ''):
                return Image.open(BytesIO(response.content))
        except Exception as e:
            self.log(f"Error WMS: {e}")
        return None

    def _descargar_cmup_wfs(self) -> Optional[gpd.GeoDataFrame]:
        """
        Descarga los polígonos del Catálogo de Montes de Utilidad Pública vía WFS.
        
        Returns:
            GeoDataFrame con los polígonos CMUP o None si hay error
        """
        url_wfs = "https://wms.mapama.gob.es/sig/Biodiversidad/IEPF_CMUP"
        capa_wfs = "IEPF_CMUP:CMUP_Poligono"
        
        try:
            url = (
                f"{url_wfs}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&"
                f"TYPENAME={capa_wfs}&SRSNAME=EPSG:4326"
            )
            
            self.log("Descargando CMUP vía WFS...")
            
            response = self.session.get(url, timeout=60)
            response.raise_for_status()

            # Si el servidor devuelve un error XML, no es un GML válido
            if "ExceptionReport" in response.text:
                self.log(f"El servidor WFS devolvió un error.")
                return None

            # Leer GML directamente desde la memoria para evitar problemas con archivos temporales
            gdf = gpd.read_file(response.text, driver="GML")
            
            self.log(f"{len(gdf)} polígonos descargados...")
            return gdf
            
        except Exception as e:
            self.log(f"Error WFS: {e}")
            return None

    def _generar_plano_montes_publicos(self, carpeta: Path) -> None:
        """
        Genera plano de Montes de Utilidad Pública (CMUP/IEPF).
        
        Descarga los polígonos oficiales vía WFS del MITECO y los superpone
        sobre ortofoto PNOA con la leyenda oficial.
        
        Args:
            carpeta: Carpeta con KML y donde guardar el plano
        """
        self.log(f"🌲 Generando Plano Montes Públicos (CMUP)...")
        
        kml = carpeta / "MAPA_MAESTRO_TOTAL.kml"
        
        if not kml.exists():
            self.log("⚠️ KML no encontrado")
            return
        
        try:
            # 1) Leer KML de las parcelas
            gdf_kml = gpd.read_file(str(kml), driver="KML")
            if gdf_kml.empty:
                self.log("⚠️ KML vacío")
                return
            
            gdf_kml_3857 = gdf_kml.to_crs(3857)
            minx, miny, maxx, maxy = gdf_kml_3857.total_bounds
            cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
            
            margin = 5000
            bbox = [cx - margin, cy - margin * 0.75, cx + margin, cy + margin * 0.75]
            
            # 2) Descargar CMUP vía WFS
            gdf_cmup = self._descargar_cmup_wfs()
            if gdf_cmup is None or gdf_cmup.empty:
                self.log("⚠️ Sin datos CMUP")
                return
            
            # 3) Recortar CMUP al área del KML
            gdf_cmup = gdf_cmup.to_crs(3857)
            gdf_clip = gpd.overlay(gdf_cmup, gdf_kml_3857, how="intersection")
            
            # 4) Descargar ortofoto PNOA
            url_pnoa = "https://www.ign.es/wms-inspire/pnoa-ma"
            params_base = {
                "SERVICE": "WMS",
                "VERSION": "1.1.1",
                "REQUEST": "GetMap",
                "LAYERS": "OI.OrthoimageCoverage",
                "STYLES": "",
                "SRS": "EPSG:3857",
                "BBOX": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
                "WIDTH": "1500",
                "HEIGHT": "1125",
                "FORMAT": "image/jpeg"
            }
            img_base = self._descargar_imagen_wms(url_pnoa, params_base)
            
            # 5) Descargar leyenda del WMS de CMUP
            url_wms = "https://wms.mapama.gob.es/sig/Biodiversidad/IEPF_CMUP"
            capa_wms = "AM.ForestManagementArea"
            
            params_leyenda = {
                "SERVICE": "WMS",
                "VERSION": "1.1.1",
                "REQUEST": "GetLegendGraphic",
                "LAYER": capa_wms,
                "FORMAT": "image/png"
            }
            img_leyenda = self._descargar_imagen_wms(url_wms, params_leyenda)
            
            # 6) Dibujar plano
            fig = plt.figure(figsize=(12, 9))
            ax = fig.add_axes([0, 0, 1, 1])
            
            # Fondo: ortofoto
            if img_base:
                ax.imshow(img_base, extent=[bbox[0], bbox[2], bbox[1], bbox[3]])
            
            # Polígonos CMUP reales (WFS) en verde
            if not gdf_clip.empty:
                gdf_clip.plot(ax=ax, facecolor="none", edgecolor="#00AA00",
                              linewidth=2.0, zorder=10)
            
            # Parcelas KML en azul
            gdf_kml_3857.plot(ax=ax, facecolor="none", edgecolor="#0000FF",
                              linewidth=1.5, zorder=11)
            
            # Marcador rojo
            ax.plot(cx, cy, marker='v', color='#CC0000', markersize=22,
                    markeredgecolor='white', markeredgewidth=2.5, alpha=0.9, zorder=12)
            
            # Leyenda en esquina inferior izquierda
            if img_leyenda:
                ax_leg = fig.add_axes([0.01, 0.01, 0.12, 0.15])
                ax_leg.imshow(img_leyenda)
                ax_leg.axis("off")
            
            ax.set_xlim(bbox[0], bbox[2])
            ax.set_ylim(bbox[1], bbox[3])
            ax.set_axis_off()
            
            ruta_final = carpeta / "PLANO-MONTES-PUBLICOS.jpg"
            plt.savefig(ruta_final, dpi=150, bbox_inches=None, pad_inches=0,
                        pil_kwargs={'quality': 95})
            plt.close()
            
            self.log("   ✅ Generado correctamente")
            
        except Exception as e:
            self.log(f"❌ Error: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # PASO 19: PLANO VÍAS PECUARIAS 🆕
    # ═══════════════════════════════════════════════════════════════════════

    def _generar_plano_vias_pecuarias(self, carpeta: Path) -> None:
        """
        Genera plano de Vías Pecuarias desde GPKG local.
        
        Utiliza el archivo RGVP2024.gpkg (Red de Vías Pecuarias) con clasificación
        por tipo (Cañadas, Cordeles, Veredas, etc.) sobre fondo OpenStreetMap.
        
        Args:
            carpeta: Carpeta con KML y donde guardar el plano
        """
        self.log(f"🐄 Generando Plano Vías Pecuarias...")
        
        kml = carpeta / "MAPA_MAESTRO_TOTAL.kml"
        
        if not kml.exists():
            self.log("⚠️ KML no encontrado")
            return
        
        # Ruta al GPKG de Vías Pecuarias
        gpkg_vvpp = self.fuentes / "CAPAS_gpkg" / "afecciones" / "RGVP2024.gpkg"
        
        if not gpkg_vvpp.exists():
            self.log(f"⚠️ GPKG no encontrado: {gpkg_vvpp}")
            return
        
        try:
            # 1) Leer KML y convertir a EPSG:3857
            self.log("   Leyendo KML...")
            gdf = gpd.read_file(str(kml), driver="KML")
            gdf_3857 = gdf.to_crs(epsg=3857)
            
            # 2) Calcular área de búsqueda
            minx, miny, maxx, maxy = gdf_3857.total_bounds
            margen = 5000  # 5km de margen
            area_busqueda = box(minx - margen, miny - margen, maxx + margen, maxy + margen)
            
            # 3) Cargar Vías Pecuarias con filtro espacial
            self.log("   Cargando Vías Pecuarias...")
            vvpp = gpd.read_file(str(gpkg_vvpp), bbox=area_busqueda)
            vvpp_3857 = vvpp.to_crs(epsg=3857)
            
            # 4) Crear figura
            fig = plt.figure(figsize=(12, 12))
            ax = fig.add_axes([0, 0, 1, 1])
            
            # Establecer límites antes del basemap
            ax.set_xlim(minx - margen, maxx + margen)
            ax.set_ylim(miny - margen, maxy + margen)
            
            # 5) Añadir fondo OpenStreetMap
            self.log("   Añadiendo basemap...")
            try:
                cx.add_basemap(ax, source=cx.providers.OpenStreetMap.Mapnik)
            except Exception as e:
                self.log(f"⚠️ Error basemap: {e}...")
            
            # 6) Dibujar Vías Pecuarias si existen
            if not vvpp_3857.empty:
                self.log(f"   Encontradas {len(vvpp_3857)} vías...")
                
                # Usar columna de clasificación si existe
                columna_label = "FC_CLASIF" if "FC_CLASIF" in vvpp_3857.columns else None
                
                vvpp_3857.plot(
                    ax=ax,
                    linewidth=4,
                    column=columna_label,
                    cmap="viridis",
                    zorder=5,
                    alpha=0.7,
                    legend=True,
                    legend_kwds={
                        'loc': 'lower left',
                        'title': 'Vías Pecuarias',
                        'fontsize': 'large'
                    }
                )
            else:
                self.log("⚠️ Sin vías pecuarias en esta zona...")
            
            # 7) Dibujar parcela (KML) en azul
            gdf_3857.plot(ax=ax, facecolor="none", edgecolor="blue",
                          linewidth=3, zorder=10)
            
            # 8) Marcador en centroide
            centro = gdf_3857.geometry.centroid.iloc[0]
            ax.plot(centro.x, centro.y, marker="v", color="red", markersize=25,
                    markeredgecolor="white", markeredgewidth=2, zorder=15)
            
            ax.set_axis_off()
            
            # 9) Guardar
            ruta_final = carpeta / "PLANO-VIAS-PECUARIAS.jpg"
            plt.savefig(ruta_final, dpi=150, bbox_inches=None, pad_inches=0)
            plt.close()
            
            self.log("   ✅ Generado correctamente")
            
        except Exception as e:
            self.log(f"❌ Error: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    """
    Ejecuta el orquestador desde el directorio donde se encuentra el script.
    
    Uso:
        python orquestador_completo_final.py
    
    El script buscará archivos .txt en la carpeta INPUTS y generará todos
    los productos cartográficos en OUTPUTS.
    """
    base = Path(__file__).resolve().parent
    
    print(f"\n{'═'*80}")
    print(f"║{'ORQUESTADOR PIPELINE GIS CATASTRAL'.center(78)}║")
    print(f"║{'Scripts 1-19 Integrados'.center(78)}║")
    print(f"{'═'*80}\n")
    print(f"📂 Directorio base: {base}")
    print(f"📥 Buscando archivos .txt en: {base / 'INPUTS'}")
    print(f"📤 Resultados se guardarán en: {base / 'OUTPUTS'}\n")
    
    orquestador = OrquestadorPipeline(base)
    orquestador.run()
    
    print(f"\n{'═'*80}")
    print(f"║{'PIPELINE FINALIZADO'.center(78)}║")
    print(f"{'═'*80}\n")

# ═══════════════════════════════════════════════════════════════════════
# FUNCIÓN AUXILIAR: EXPLORAR ESTRUCTURA DE UNA CAPA
# ═══════════════════════════════════════════════════════════════════════
def explorar_capa(ruta_capa: Path) -> None:
    """
    Herramienta de diagnóstico para ver qué contiene una capa.
    Útil para identificar columnas relevantes.
    """
    import geopandas as gpd
    
    print(f"\n{'='*60}")
    print(f"EXPLORANDO: {ruta_capa.name}")
    print(f"{'='*60}")
    
    try:
        gdf = gpd.read_file(str(ruta_capa))
        
        print(f"📊 Registros: {len(gdf)}")
        print(f"📐 CRS: {gdf.crs}")
        print(f"📏 Tipos de geometría: {gdf.geometry.type.unique()}")
        print(f"\n📋 Columnas disponibles:")
        
        for col in gdf.columns:
            if col != 'geometry':
                # Mostrar algunos valores de ejemplo
                valores_unicos = gdf[col].dropna().unique()[:5]
                print(f"   • {col}: {list(valores_unicos)}")
        
        print(f"\n📍 Extent (bounds):")
        print(f"   {gdf.total_bounds}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    
    print(f"{'='*60}\n")
