"""
Módulo optimizado para descarga de información catastral.
- Con cache de peticiones HTTP
- Coordenadas unificadas
- Parámetros avanzados
- Paralelización opcional
"""

import requests
import requests_cache
import os
from pathlib import Path
import time
import xml.etree.ElementTree as ET
import json
from io import BytesIO
from datetime import datetime
import zipfile
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
import csv

# Intentar importar dependencias opcionales
try:
    from PIL import Image, ImageDraw
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    print("⚠ Pillow no disponible - funciones de imagen deshabilitadas")

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    print("⚠ ReportLab no disponible - generación de PDF deshabilitada")

try:
    from pyproj import Transformer
    PYPROJ_AVAILABLE = True
except ImportError:
    PYPROJ_AVAILABLE = False
    print("⚠ pyproj no disponible - conversión UTM aproximada")

class CatastroDownloader:
    """
    Descargador optimizado de documentación catastral.
    Con cache HTTP y procesamiento mejorado.
    """
    
    def __init__(self, output_dir="descargas_catastro", cache_hours=1, max_workers=3):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # Configurar cache HTTP (1 hora por defecto)
        self.session = requests_cache.CachedSession(
            'catastro_cache',
            expire_after=cache_hours * 3600,
            allowable_methods=('GET', 'POST'),
            stale_if_error=True
        )
        self.session.verify = False # Evitar errores de certificado en servidores oficiales

        
        # Configuración de paralelización
        self.max_workers = max_workers
        
        # URLs base
        self.base_urls = {
            'catastro_wms': "https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx",
            'inspire_wfs': "https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx",
            'sedecatastro': "https://www1.sedecatastro.gob.es",
            'ign_pnoa': "https://www.ign.es/wms-inspire/pnoa-ma",
            'idee': "https://www.idee.es/wms"
        }
        
        # Cache local para datos frecuentes
        self._municipio_cache = {}
        self._coordenadas_cache = {}
        
        print(f"✅ Descargador inicializado. Cache: {cache_hours}h, Workers: {max_workers}")
    
    def limpiar_referencia(self, ref):
        """Limpia referencia catastral"""
        return ref.replace(" ", "").replace("-", "").strip().upper()
    
    @lru_cache(maxsize=100)
    def extraer_del_mun(self, ref):
        """Extrae delegación y municipio (con cache)"""
        ref = self.limpiar_referencia(ref)
        if len(ref) >= 5:
            return ref[:2], ref[2:5]
        return "", ""
    
    def obtener_coordenadas_unificado(self, referencia):
        """
        Método unificado para obtener coordenadas.
        Intenta múltiples fuentes con cache.
        """
        ref = self.limpiar_referencia(referencia)
        
        # Verificar cache
        if ref in self._coordenadas_cache:
            return self._coordenadas_cache[ref]
        
        metodos = [
            self._obtener_coordenadas_json,
            self._obtener_coordenadas_gml,
            self._obtener_coordenadas_xml
        ]
        
        for metodo in metodos:
            try:
                coords = metodo(ref)
                if coords:
                    self._coordenadas_cache[ref] = coords
                    print(f"  ✓ Coordenadas obtenidas ({metodo.__name__})")
                    return coords
            except Exception as e:
                continue
        
        print(f"  ✗ No se pudieron obtener coordenadas para {ref}")
        return None
    
    def convertir_a_utm(self, lon, lat):
        """Convierte Lat/Lon a UTM (ETRS89)"""
        huso = 30 # Por defecto para gran parte de España
        if lon > 0: huso = 31
        elif lon < -6: huso = 29
        
        if PYPROJ_AVAILABLE:
            try:
                transformer = Transformer.from_crs("EPSG:4326", f"EPSG:258{huso}", always_xy=True)
                x, y = transformer.transform(lon, lat)
                return x, y, huso
            except:
                pass
        
        # Aproximación simple si falla pyproj (solo para referencia visual)
        # Esto NO es preciso, solo para rellenar huecos si falta la librería
        x = (lon + 180) * 100000 # Dummy
        y = (lat + 90) * 100000  # Dummy
        return x, y, huso

    def _obtener_coordenadas_json(self, ref):
        """Obtener coordenadas desde servicio JSON"""
        url = f"https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/COVCCallejero.svc/json/Geo_RCToWGS84/{ref}"
        
        try:
            response = self.session.get(url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                if "geo" in data and "xcen" in data["geo"] and "ycen" in data["geo"]:
                    lon = float(data["geo"]["xcen"])
                    lat = float(data["geo"]["ycen"])
                    return {"lon": lon, "lat": lat, "srs": "EPSG:4326", "fuente": "JSON"}
        except:
            pass
        return None
    
    def _obtener_coordenadas_gml(self, ref):
        """Obtener coordenadas desde GML"""
        params = {
            "service": "wfs",
            "version": "2.0.0",
            "request": "GetFeature",
            "STOREDQUERY_ID": "GetParcel",
            "refcat": ref,
            "srsname": "EPSG:4326",
        }
        
        try:
            response = self.session.get(self.base_urls['inspire_wfs'], params=params, timeout=15)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                
                # Buscar coordenadas en múltiples namespaces
                namespaces = {
                    "gml": "http://www.opengis.net/gml/3.2",
                    "cp": "http://inspire.ec.europa.eu/schemas/cp/4.0",
                    "gmd": "http://www.isotc211.org/2005/gmd",
                }
                
                for ns_uri in namespaces.values():
                    pos_list = root.findall(f".//{{{ns_uri}}}pos")
                    if pos_list:
                        coords_text = pos_list[0].text.strip().split()
                        if len(coords_text) >= 2:
                            v1, v2 = float(coords_text[0]), float(coords_text[1])
                            
                            # Determinar si es (lat, lon) o (lon, lat)
                            if 36 <= v1 <= 44 and -10 <= v2 <= 5:
                                lat, lon = v1, v2
                            elif 36 <= v2 <= 44 and -10 <= v1 <= 5:
                                lat, lon = v2, v1
                            else:
                                lat, lon = v1, v2
                            
                            return {"lon": lon, "lat": lat, "srs": "EPSG:4326", "fuente": "GML"}
        except:
            pass
        return None
    
    def _obtener_coordenadas_xml(self, ref):
        """Obtener coordenadas desde servicio XML"""
        url = "https://ovc.catastro.meh.es/ovcservweb/ovcswlocalizacionrc/ovccoordenadas.asmx/Consulta_RCCOOR"
        params = {"SRS": "EPSG:4326", "RC": ref}
        
        try:
            response = self.session.get(url, params=params, timeout=15)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                ns = {"cat": "http://www.catastro.meh.es/"}
                
                coord_element = root.find(".//cat:coord", ns)
                if coord_element is not None:
                    geo = coord_element.find("cat:geo", ns)
                    if geo is not None:
                        xcen = geo.find("cat:xcen", ns)
                        ycen = geo.find("cat:ycen", ns)
                        
                        if xcen is not None and ycen is not None:
                            lon = float(xcen.text)
                            lat = float(ycen.text)
                            return {"lon": lon, "lat": lat, "srs": "EPSG:4326", "fuente": "XML"}
        except:
            pass
        return None

    def obtener_datos_alfanumericos(self, referencia):
        """
        Obtiene datos alfanuméricos (usos, superficies, año constr.) del servicio XML Consulta_DNPRC.
        Este XML contiene la 'información completa' que no está en el GML.
        """
        ref = self.limpiar_referencia(referencia)
        url = "http://ovc.catastro.meh.es/ovcservweb/OVCSWLocalizacionRC/OVCCallejero.asmx/Consulta_DNPRC"
        params = {
            "Provincia": "",
            "Municipio": "",
            "RC": ref
        }
        
        datos = {
            "referencia": ref,
            "domicilio": "No disponible",
            "uso_principal": "No disponible",
            "superficie_construida": 0,
            "anio_construccion": "N/D",
            "bienes": [] # Lista de sub-unidades (usos)
        }
        
        try:
            response = self.session.get(url, params=params, timeout=15)
            if response.status_code == 200:
                # Guardar el XML original
                xml_path = self.output_dir / f"{ref}_datos.xml"
                with open(xml_path, "wb") as f:
                    f.write(response.content)
                print(f"  ✓ XML de datos guardado: {xml_path.name}")
                
                root = ET.fromstring(response.content)
                ns = {"cat": "http://www.catastro.meh.es/"}
                
                # Domicilio
                ldt = root.find(".//cat:ldt", ns)
                if ldt is not None:
                    datos["domicilio"] = ldt.text
                
                # Datos de la finca (bico)
                bico = root.find(".//cat:bico", ns)
                if bico is not None:
                    bi = bico.find("cat:bi", ns)
                    if bi is not None:
                        datos["uso_principal"] = bi.find("cat:ldt", ns).text if bi.find("cat:ldt", ns) is not None else "N/D"
                        
                        debi = bi.find("cat:debi", ns)
                        if debi is not None:
                            sfc = debi.find("cat:sfc", ns)
                            datos["superficie_construida"] = int(sfc.text) if sfc is not None else 0
                            ant = debi.find("cat:ant", ns)
                            datos["anio_construccion"] = ant.text if ant is not None else "N/D"
                
                # Lista de construcciones/usos (lcons)
                for cons in root.findall(".//cat:lcons/cat:cons", ns):
                    uso = cons.find("cat:lcd", ns).text if cons.find("cat:lcd", ns) is not None else ""
                    sup = cons.find("cat:dfcons/cat:stl", ns)
                    sup_val = int(sup.text) if sup is not None else 0
                    datos["bienes"].append({
                        "uso": uso,
                        "superficie": sup_val
                    })
                    
            return datos
        except Exception as e:
            print(f"  ⚠ Error obteniendo datos alfanuméricos XML: {e}")
            return None
    
    def calcular_bbox_optimizado(self, coords_centrales=None, coords_poligono=None, buffer_metros=200):
        """
        Calcula BBOX optimizado para WMS.
        Prioriza polígono si existe, sino usa punto central.
        """
        if coords_poligono and len(coords_poligono) > 1:
            # Calcular bbox del polígono
            lons = [c[1] if self._es_latitud(c[0]) else c[0] for c in coords_poligono]
            lats = [c[0] if self._es_latitud(c[0]) else c[1] for c in coords_poligono]
            
            lon_min, lon_max = min(lons), max(lons)
            lat_min, lat_max = min(lats), max(lats)
            
            # Añadir buffer (10% del tamaño)
            lon_buffer = (lon_max - lon_min) * 0.1
            lat_buffer = (lat_max - lat_min) * 0.1
            
            return f"{lon_min - lon_buffer},{lat_min - lat_buffer},{lon_max + lon_buffer},{lat_max + lat_buffer}"
        
        elif coords_centrales:
            # Usar punto central con buffer fijo
            lon, lat = coords_centrales["lon"], coords_centrales["lat"]
            buffer_lon = buffer_metros / 85000
            buffer_lat = buffer_metros / 111000
            
            return f"{lon - buffer_lon},{lat - buffer_lat},{lon + buffer_lon},{lat + buffer_lat}"
        
        return None
    
    def _es_latitud(self, valor):
        """Determina si un valor es probablemente latitud"""
        return 36 <= valor <= 44
    
    def descargar_paralelo(self, referencias, callback=None):
        """
        Descarga múltiples referencias en paralelo.
        
        Args:
            referencias: Lista de referencias
            callback: Función para notificar progreso (opcional)
        
        Returns:
            Lista de resultados
        """
        resultados = []
        total = len(referencias)
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Enviar todas las tareas
            futures = {
                executor.submit(self.descargar_todo, ref): ref 
                for ref in referencias
            }
            
            # Procesar resultados conforme se completan
            for i, future in enumerate(as_completed(futures), 1):
                ref = futures[future]
                try:
                    resultado = future.result(timeout=300)  # 5 minutos por referencia
                    resultados.append((ref, resultado))
                    
                    if callback:
                        callback(i, total, ref, resultado)
                
                except Exception as e:
                    print(f"✗ Error procesando {ref}: {e}")
                    resultados.append((ref, {"error": str(e)}))
        
        return resultados
    
    def descargar_ortofotos_contexto(self, referencia, coords, coords_poligono=None):
        """Descarga ortofotos de contexto (Nacional, Autonómico, Provincial) y dibuja contorno"""
        ref = self.limpiar_referencia(referencia)
        lon, lat = coords['lon'], coords['lat']
        
        # Niveles de zoom (buffer en metros aprox)
        niveles = [
            ("provincial", 25000),   # ~50km ancho
            ("autonomico", 100000),  # ~200km ancho
            ("nacional", 400000)     # ~800km ancho
        ]
        
        resultados = {}
        
        for nombre, buffer in niveles:
            try:
                # Calcular BBOX
                buffer_lon = buffer / 85000
                buffer_lat = buffer / 111000
                bbox = f"{lon - buffer_lon},{lat - buffer_lat},{lon + buffer_lon},{lat + buffer_lat}"
                
                # Preparar BBOX para WMS 1.3.0 (Lat, Lon)
                coords_bbox = [float(x) for x in bbox.split(",")]
                bbox_wms13 = f"{coords_bbox[1]},{coords_bbox[0]},{coords_bbox[3]},{coords_bbox[2]}"
                
                # Descargar PNOA
                params = {
                    "SERVICE": "WMS",
                    "VERSION": "1.3.0",
                    "REQUEST": "GetMap",
                    "LAYERS": "OI.OrthoimageCoverage",
                    "STYLES": "",
                    "CRS": "EPSG:4326",
                    "BBOX": bbox_wms13,
                    "WIDTH": "2500", 
                    "HEIGHT": "2500",
                    "FORMAT": "image/jpeg",
                }
                
                response = self.session.get(self.base_urls['ign_pnoa'], params=params, timeout=60)
                
                if response.status_code == 200 and len(response.content) > 5000:
                    filename = f"{ref}_ortofoto_{nombre}.jpg"
                    filepath = self.output_dir / filename
                    with open(filepath, 'wb') as f:
                        f.write(response.content)
                    
                    print(f"  ✓ Ortofoto {nombre} descargada")
                    resultados[nombre] = True
                    
                    # Dibujar contorno si es posible
                    if PILLOW_AVAILABLE and coords_poligono:
                        # Pasar solo el primer anillo (exterior) para dibujar
                        anillo_exterior = coords_poligono[0] if isinstance(coords_poligono[0], list) else coords_poligono
                        self._dibujar_contorno_en_imagen(filepath, filepath, anillo_exterior, bbox)
                        
                else:
                    print(f"  ⚠ Error descargando ortofoto {nombre}")
                    
            except Exception as e:
                print(f"  ⚠ Excepción en ortofoto {nombre}: {e}")
                
        return resultados

    def _dibujar_contorno_en_imagen(self, img_path, out_path, coords_poligono, bbox_wgs84):
        """Helper para dibujar contorno en una imagen dado su bbox"""
        try:
            with Image.open(img_path) as img:
                img = img.convert("RGBA")
                overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(overlay)
                
                width, height = img.size
                
                coords_bbox = [float(x) for x in bbox_wgs84.split(",")]
                minx, miny, maxx, maxy = coords_bbox
                
                pixels = []
                for coord in coords_poligono:
                    if self._es_latitud(coord[0]):
                        lat, lon = coord[0], coord[1]
                    else:
                        lon, lat = coord[0], coord[1]
                    
                    x = int(((lon - minx) / (maxx - minx)) * width)
                    y = int(((maxy - lat) / (maxy - miny)) * height)
                    pixels.append((x, y))
                
                # Si el polígono es muy pequeño (vista nacional), dibujar un punto/círculo
                xs = [p[0] for p in pixels]
                ys = [p[1] for p in pixels]
                if xs and ys:
                    w_px = max(xs) - min(xs)
                    h_px = max(ys) - min(ys)
                    
                    if w_px < 10 and h_px < 10:
                        cx = sum(xs) / len(xs)
                        cy = sum(ys) / len(ys)
                        r = 6
                        draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(255, 0, 0, 255), outline=(255, 255, 255, 255))
                    elif len(pixels) > 2:
                        # Relleno rojo semitransparente
                        draw.polygon(pixels, fill=(255, 0, 0, 60))
                        # Borde rojo sólido
                        draw.line(pixels + [pixels[0]], fill=(255, 0, 0, 255), width=3)
                
                result = Image.alpha_composite(img, overlay).convert("RGB")
                result.save(out_path)
                return True
        except Exception as e:
            print(f"  ⚠ Error dibujando contorno en {img_path.name}: {e}")
            return False

    def descargar_todo(self, referencia, crear_zip=False, descargar_afecciones=True):
        """
        Descarga todos los documentos para una referencia.
        
        Args:
            referencia: Referencia catastral
            crear_zip: Crear archivo ZIP
            descargar_afecciones: Descargar capas de afecciones
        
        Returns:
            Diccionario con resultados
        """
        print(f"\n{'='*60}")
        print(f"📥 Procesando: {referencia}")
        print(f"{'='*60}")
        
        ref = self.limpiar_referencia(referencia)
        ref_dir = self.output_dir / ref
        ref_dir.mkdir(exist_ok=True)
        
        # Guardar directorio original
        old_dir = self.output_dir
        self.output_dir = ref_dir
        
        resultados = {
            'referencia': ref,
            'timestamp': datetime.now().isoformat(),
            'exitosa': False
        }
        
        try:
            # 1. Obtener coordenadas
            coords = self.obtener_coordenadas_unificado(ref)
            if not coords:
                print("  ✗ No se pudieron obtener coordenadas")
                return resultados
            
            resultados['coordenadas'] = coords
            
            # 2. Descargar GML de parcela
            parcela_gml = self.descargar_parcela_gml(ref)
            resultados['parcela_gml'] = parcela_gml
            
            # 2b. Descargar Datos Alfanuméricos (XML)
            datos_xml = self.obtener_datos_alfanumericos(ref)
            resultados['datos_xml'] = datos_xml is not None
            
            # 3. Descargar GML de edificio (si existe)
            edificio_gml = self.descargar_edificio_gml(ref)
            resultados['edificio_gml'] = edificio_gml
            
            # 4. Extraer coordenadas del polígono
            coords_poligono = None
            if parcela_gml:
                gml_file = ref_dir / f"{ref}_parcela.gml"
                coords_poligono = self.extraer_coordenadas_gml(str(gml_file))
            
            # 5. Calcular BBOX
            bbox = self.calcular_bbox_optimizado(coords, coords_poligono)
            resultados['bbox'] = bbox
            
            # 6. Generar KML
            kml_generado = self.generar_kml(ref, coords, coords_poligono)
            resultados['kml'] = kml_generado
            
            # 7. Descargar plano y ortofoto
            plano_descargado = self.descargar_plano_ortofoto(ref, bbox)
            resultados['plano_ortofoto'] = plano_descargado
            # Aplanar resultados para acceso directo
            if isinstance(plano_descargado, dict):
                resultados.update(plano_descargado)
            
            # 8. Descargar PDF oficial
            pdf_descargado = self.descargar_consulta_descriptiva_pdf(ref)
            resultados['pdf_oficial'] = pdf_descargado
            
            # 9. Descargar capas de afecciones (si está habilitado)
            if descargar_afecciones and bbox:
                afecciones = self.descargar_capas_afecciones(ref, bbox)
                resultados['capas_afecciones'] = afecciones
            
            # 10. Descargar ortofotos contexto (Nacional, Autonómico, Provincial)
            if bbox:
                ctx = self.descargar_ortofotos_contexto(ref, coords, coords_poligono)
                # Añadir con prefijo para evitar colisiones
                for k, v in ctx.items():
                    resultados[f'ortofoto_{k}'] = v

            # 11. Superponer contornos (Local)
            if PILLOW_AVAILABLE and coords_poligono and bbox:
                contorno_superpuesto = self.superponer_contorno_parcela(ref, bbox)
                resultados['contorno_superpuesto'] = contorno_superpuesto
            
            # 12. Generar informe PDF (AHORA AL FINAL para incluir imágenes con contorno)
            if REPORTLAB_AVAILABLE:
                try:
                    informe_generado = self.generar_informe_pdf(ref)
                    resultados['informe_pdf'] = informe_generado
                except Exception as e:
                    print(f"  ⚠ Error generando informe PDF: {e}")
                    resultados['informe_pdf'] = False
            
            # 12. Crear ZIP si se solicita
            if crear_zip:
                zip_path = self.crear_zip_referencia(ref, str(old_dir))
                resultados['zip_generado'] = zip_path is not None
                resultados['zip_path'] = zip_path
            
            resultados['exitosa'] = True
            
            # Mostrar resumen
            self._mostrar_resumen(resultados)
            
        except Exception as e:
            print(f"  ✗ Error en procesamiento: {e}")
            import traceback
            traceback.print_exc()
            resultados['error'] = str(e)
        
        finally:
            # Restaurar directorio original
            self.output_dir = old_dir
        
        return resultados
    
    def descargar_parcela_gml(self, referencia):
        """Descarga GML de parcela"""
        ref = self.limpiar_referencia(referencia)
        filename = self.output_dir / f"{ref}_parcela.gml"
        
        if filename.exists():
            print(f"  ↩ GML ya existe: {filename.name}")
            return True
        
        params = {
            'service': 'wfs',
            'version': '2.0.0',
            'request': 'GetFeature',
            'STOREDQUERY_ID': 'GetParcel',
            'refcat': ref,
            'srsname': 'EPSG:4326'
        }
        
        try:
            response = self.session.get(self.base_urls['inspire_wfs'], params=params, timeout=30)
            
            if response.status_code == 200:
                # Verificar que no sea un error
                if b'ExceptionReport' in response.content:
                    print(f"  ⚠ Parcela GML no disponible")
                    return False
                
                with open(filename, 'wb') as f:
                    f.write(response.content)
                print(f"  ✓ Parcela GML descargada: {filename.name}")
                return True
            else:
                print(f"  ✗ Error HTTP {response.status_code}")
                return False
                
        except Exception as e:
            print(f"  ✗ Error: {e}")
            return False
    
    def descargar_edificio_gml(self, referencia):
        """Descarga GML de edificio"""
        ref = self.limpiar_referencia(referencia)
        filename = self.output_dir / f"{ref}_edificio.gml"
        
        if filename.exists():
            print(f"  ↩ Edificio GML ya existe: {filename.name}")
            return True
        
        params = {
            'service': 'wfs',
            'version': '2.0.0',
            'request': 'GetFeature',
            'STOREDQUERY_ID': 'GetBuilding',
            'refcat': ref,
            'srsname': 'EPSG:4326'
        }
        
        try:
            response = self.session.get(self.base_urls['inspire_wfs'], params=params, timeout=30)
            
            if response.status_code == 200:
                if b'ExceptionReport' in response.content:
                    print(f"  ⚠ Edificio GML no disponible (puede ser solo parcela)")
                    return False
                
                with open(filename, 'wb') as f:
                    f.write(response.content)
                print(f"  ✓ Edificio GML descargado: {filename.name}")
                return True
            else:
                print(f"  ✗ Error HTTP {response.status_code}")
                return False
                
        except Exception as e:
            print(f"  ✗ Error: {e}")
            return False
    
    def descargar_consulta_descriptiva_pdf(self, referencia):
        """Descarga PDF oficial de consulta descriptiva"""
        ref = self.limpiar_referencia(referencia)
        del_code, mun_code = self.extraer_del_mun(ref)
        
        filename = self.output_dir / f"{ref}_consulta_oficial.pdf"
        
        if filename.exists():
            print(f"  ↩ PDF oficial ya existe: {filename.name}")
            return True
        
        url = f"{self.base_urls['sedecatastro']}/CYCBienInmueble/SECImprimirCroquisYDatos.aspx"
        params = {
            'del': del_code,
            'mun': mun_code,
            'refcat': ref
        }
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            
            if (response.status_code == 200 and 
                'application/pdf' in response.headers.get('Content-Type', '')):
                
                with open(filename, 'wb') as f:
                    f.write(response.content)
                print(f"  ✓ PDF oficial descargado: {filename.name}")
                return True
            else:
                print(f"  ✗ PDF no disponible (Status: {response.status_code})")
                return False
                
        except Exception as e:
            print(f"  ✗ Error: {e}")
            return False
    
    def descargar_plano_ortofoto(self, referencia, bbox_wgs84):
        """Descarga plano catastral y ortofoto"""
        ref = self.limpiar_referencia(referencia)
        
        print("  🗺️  Descargando plano y ortofoto...")
        
        # Preparar BBOX para diferentes versiones WMS
        coords = [float(x) for x in bbox_wgs84.split(",")]
        bbox_wms11 = bbox_wgs84
        bbox_wms13 = f"{coords[1]},{coords[0]},{coords[3]},{coords[2]}"  # miny,minx,maxy,maxx
        
        resultados = {
            'plano_catastro': False,
            'ortofoto_pnoa': False,
            'composicion': False
        }
        
        # 1. Descargar plano catastral (WMS 1.1.1)
        try:
            params = {
                "SERVICE": "WMS",
                "VERSION": "1.1.1",
                "REQUEST": "GetMap",
                "LAYERS": "Catastro",
                "STYLES": "",
                "SRS": "EPSG:4326",
                "BBOX": bbox_wms11,
                "WIDTH": "2400",
                "HEIGHT": "2400",
                "FORMAT": "image/png",
                "TRANSPARENT": "FALSE",
            }
            
            response = self.session.get(self.base_urls['catastro_wms'], params=params, timeout=60)
            
            if response.status_code == 200 and len(response.content) > 1000:
                plano_file = self.output_dir / f"{ref}_plano_catastro.png"
                with open(plano_file, 'wb') as f:
                    f.write(response.content)
                print(f"  ✓ Plano catastral descargado")
                resultados['plano_catastro'] = True
            else:
                print(f"  ✗ Error descargando plano")
        
        except Exception as e:
            print(f"  ✗ Error plano: {e}")
        
        # 2. Descargar ortofoto PNOA (WMS 1.3.0)
        try:
            params = {
                "SERVICE": "WMS",
                "VERSION": "1.3.0",
                "REQUEST": "GetMap",
                "LAYERS": "OI.OrthoimageCoverage",
                "STYLES": "",
                "CRS": "EPSG:4326",
                "BBOX": bbox_wms13,
                "WIDTH": "2400",
                "HEIGHT": "2400",
                "FORMAT": "image/png",
            }
            
            response = self.session.get(self.base_urls['ign_pnoa'], params=params, timeout=60)
            
            if response.status_code == 200 and len(response.content) > 8000:
                orto_file = self.output_dir / f"{ref}_ortofoto_pnoa.jpg"
                with open(orto_file, 'wb') as f:
                    f.write(response.content)
                print(f"  ✓ Ortofoto PNOA descargada")
                resultados['ortofoto_pnoa'] = True
                
                # 3. Crear composición si ambas imágenes existen
                if resultados['plano_catastro'] and PILLOW_AVAILABLE:
                    try:
                        plano_path = self.output_dir / f"{ref}_plano_catastro.png"
                        orto_path = self.output_dir / f"{ref}_ortofoto_pnoa.jpg"
                        
                        with Image.open(plano_path) as img_plano:
                            with Image.open(orto_path) as img_orto:
                                # Asegurar mismo tamaño: redimensionar ortofoto al tamaño del plano
                                img_orto = img_orto.resize(img_plano.size)

                                # Crear composición (mezcla suave: ortofoto predominante)
                                composicion = Image.blend(
                                    img_orto.convert("RGBA"),
                                    img_plano.convert("RGBA"),
                                    alpha=0.35
                                )

                                comp_file = self.output_dir / f"{ref}_plano_con_ortofoto.png"
                                composicion.save(comp_file, "PNG")
                                print(f"  ✓ Composición creada: {comp_file.name}")
                                resultados['composicion'] = True
                    
                    except Exception as e:
                        print(f"  ⚠ Error creando composición: {e}")
        
        except Exception as e:
            print(f"  ✗ Error ortofoto: {e}")
        
        return resultados
    
    def descargar_capas_afecciones(self, referencia, bbox_wgs84):
        """Descarga capas de afecciones territoriales"""
        ref = self.limpiar_referencia(referencia)
        
        print("  🏞️  Descargando capas de afecciones...")
        
        # Preparar BBOX
        coords = [float(x) for x in bbox_wgs84.split(",")]
        bbox_wms13 = f"{coords[1]},{coords[0]},{coords[3]},{coords[2]}"
        
        capas = {
            'catastro_parcelas': {
                'url': self.base_urls['catastro_wms'],
                'version': '1.1.1',
                'layers': 'Catastro',
                'bbox': bbox_wgs84,
                'desc': 'Plano catastral'
            },
            'planeamiento': {
                'url': f"{self.base_urls['idee']}/IDEE-Planeamiento/IDEE-Planeamiento",
                'version': '1.3.0',
                'layers': 'PlaneamientoGeneral',
                'bbox': bbox_wms13,
                'desc': 'Planeamiento urbanístico'
            }
        }
        
        descargadas = []
        
        for nombre, config in capas.items():
            try:
                params = {
                    'SERVICE': 'WMS',
                    'VERSION': config['version'],
                    'REQUEST': 'GetMap',
                    'LAYERS': config['layers'],
                    'STYLES': '',
                    'CRS': 'EPSG:4326' if config['version'] == '1.3.0' else 'SRS',
                    'BBOX': config['bbox'],
                    'WIDTH': '1200',
                    'HEIGHT': '1200',
                    'FORMAT': 'image/png',
                    'TRANSPARENT': 'TRUE'
                }
                
                if config['version'] == '1.1.1':
                    params['SRS'] = 'EPSG:4326'
                    del params['CRS']
                
                response = self.session.get(config['url'], params=params, timeout=45)
                
                if response.status_code == 200 and len(response.content) > 1000:
                    archivo = self.output_dir / f"{ref}_afeccion_{nombre}.png"
                    with open(archivo, 'wb') as f:
                        f.write(response.content)
                    
                    descargadas.append({
                        'nombre': nombre,
                        'descripcion': config['desc'],
                        'archivo': str(archivo)
                    })
                    print(f"    ✓ {config['desc']}")
                else:
                    print(f"    ⚠ {config['desc']}: Sin datos")
            
            except Exception as e:
                print(f"    ⚠ {config['desc']}: Error - {str(e)[:50]}")
        
        # Guardar informe
        if descargadas:
            informe = {
                'referencia': ref,
                'fecha': datetime.now().isoformat(),
                'capas': descargadas
            }
            
            informe_file = self.output_dir / f"{ref}_afecciones_info.json"
            with open(informe_file, 'w', encoding='utf-8') as f:
                json.dump(informe, f, indent=2, ensure_ascii=False)
            
            print(f"  ✓ Informe de afecciones guardado")
        
        return len(descargadas) > 0
    
    def extraer_coordenadas_gml(self, gml_file):
        """Extrae coordenadas de archivo GML como lista de anillos separados"""
        try:
            tree = ET.parse(gml_file)
            root = tree.getroot()
            
            anillos = []  # Lista de anillos (cada anillo es una lista de coordenadas)
            
            # Intentar diferentes namespaces
            namespaces_list = [
                {'gml': 'http://www.opengis.net/gml/3.2'},
                {'gml': 'http://www.opengis.net/gml'},
                {'gml': 'http://www.isotc211.org/2005/gml'},
                {}
            ]
            
            print(f"  🔍 Buscando coordenadas en {gml_file}")
            
            for namespaces in namespaces_list:
                # Buscar posList (formato común) - puede haber múltiples anillos
                for pos_list in root.findall('.//gml:posList', namespaces):
                    if pos_list.text:
                        partes = pos_list.text.strip().split()
                        print(f"  📝 posList encontrado con {len(partes)} valores")
                        
                        coords_anillo = []
                        for i in range(0, len(partes), 2):
                            if i + 1 < len(partes):
                                try:
                                    x, y = float(partes[i]), float(partes[i+1])
                                    # Determinar si es (lon,lat) o (lat,lon)
                                    # España: Lon entre -10 y 5, Lat entre 35 y 45
                                    if (35 <= x <= 45) and (-15 <= y <= 10):
                                        # Es (lat, lon)
                                        coords_anillo.append((x, y))
                                    elif (-15 <= x <= 10) and (35 <= y <= 45):
                                        # Es (lon, lat)
                                        coords_anillo.append((y, x))
                                    else:
                                        # Fallback o fuera de España, mantener como viene pero loguear
                                        coords_anillo.append((x, y))
                                        if not (-20 <= x <= 10 and 30 <= y <= 50): # Rango amplio
                                            print(f"    ⚠️ Coordenada posiblemente fuera de rango: {x}, {y}")
                                except ValueError:
                                    continue
                        
                        if coords_anillo:
                            # Eliminar duplicados consecutivos en este anillo
                            unique_anillo = []
                            for coord in coords_anillo:
                                if not unique_anillo or coord != unique_anillo[-1]:
                                    unique_anillo.append(coord)
                            
                            if unique_anillo:
                                anillos.append(unique_anillo)
                                print(f"  ✅ Anillo con {len(unique_anillo)} coordenadas")
                
                # Buscar pos (puntos individuales) - ignorar para polígonos
                # for pos in root.findall('.//gml:pos', namespaces):
                #     if pos.text:
                #         partes = pos.text.strip().split()
                #         if len(partes) >= 2:
                #             try:
                #                 x, y = float(partes[0]), float(partes[1])
                #                 if -180 <= x <= 180 and -90 <= y <= 90:
                #                     coords.append((y, x))  # (lat, lon)
                #                 elif -180 <= y <= 180 and -90 <= x <= 90:
                #                     coords.append((x, y))  # (lat, lon)
                #             except ValueError:
                #                 continue
                
                # Buscar coordinates (formato alternativo)
                for coordinates in root.findall('.//gml:coordinates', namespaces):
                    if coordinates.text:
                        coord_text = coordinates.text.strip().replace('\n', ' ').replace('\t', ' ')
                        puntos = coord_text.split()
                        
                        coords_anillo = []
                        for punto in puntos:
                            if ',' in punto:
                                try:
                                    x, y = map(float, punto.split(','))
                                    if -180 <= x <= 180 and -90 <= y <= 90:
                                        coords_anillo.append((y, x))  # (lat, lon)
                                    elif -180 <= y <= 180 and -90 <= x <= 90:
                                        coords_anillo.append((x, y))  # (lat, lon)
                                except ValueError:
                                    continue
                        
                        if coords_anillo:
                            # Eliminar duplicados consecutivos en este anillo
                            unique_anillo = []
                            for coord in coords_anillo:
                                if not unique_anillo or coord != unique_anillo[-1]:
                                    unique_anillo.append(coord)
                            
                            if unique_anillo:
                                anillos.append(unique_anillo)
                                print(f"  ✅ Anillo coordinates con {len(unique_anillo)} coordenadas")
                
                if anillos:
                    print(f"  ✅ Encontrados {len(anillos)} anillos separados")
                    break
            
            if anillos:
                total_coords = sum(len(anillo) for anillo in anillos)
                print(f"  🔄 Total coordenadas en {len(anillos)} anillos: {total_coords}")
                return anillos
            
        except Exception as e:
            print(f"  ⚠️ Error extrayendo coordenadas GML: {e}")
        
        return None
    
    def generar_kml(self, referencia, coords, coords_poligono=None):
        """Genera archivo KML"""
        ref = self.limpiar_referencia(referencia)
        kml_file = self.output_dir / f"{ref}_parcela.kml"
        
        lon, lat = coords['lon'], coords['lat']
        
        # Cabecera KML
        kml = f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Parcela Catastral {ref}</name>
    <description>Referencia: {ref}</description>
    
    <Style id="punto_style">
      <IconStyle>
        <scale>1.2</scale>
                    <Icon>
                    <href>https://maps.google.com/mapfiles/kml/paddle/red-circle.png</href>
                </Icon>
      </IconStyle>
    </Style>
    
    <Placemark>
      <name>Centro Parcela</name>
      <description>
        <![CDATA[
        <b>Referencia:</b> {ref}<br/>
        <b>Coordenadas:</b> {lat:.6f}°, {lon:.6f}°<br/>
        <b>Catastro:</b> <a href="https://www1.sedecatastro.gob.es/Cartografia/mapa.aspx?refcat={ref}">Ver en Catastro</a><br/>
        <b>Google Maps:</b> <a href="https://maps.google.com/?q={lat},{lon}">Abrir en Maps</a>
        ]]>
      </description>
      <styleUrl>#punto_style</styleUrl>
      <Point>
        <coordinates>{lon},{lat},0</coordinates>
      </Point>
    </Placemark>'''
        
        # Añadir polígono si existe
        if coords_poligono and len(coords_poligono) > 2:
            kml += '''
    <Style id="poligono_style">
      <LineStyle>
        <color>ff0000ff</color>
        <width>3</width>
      </LineStyle>
      <PolyStyle>
        <color>4d0000ff</color>
      </PolyStyle>
    </Style>
    
    <Placemark>
      <name>Contorno Parcela</name>
      <styleUrl>#poligono_style</styleUrl>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>'''
            
            # Añadir coordenadas
            for coord in coords_poligono:
                # Determinar orden (lat, lon) o (lon, lat)
                if self._es_latitud(coord[0]):
                    lat_c, lon_c = coord[0], coord[1]
                else:
                    lon_c, lat_c = coord[0], coord[1]
                
                kml += f"\n              {lon_c},{lat_c},0"
            
            # Cerrar polígono
            first = coords_poligono[0]
            if self._es_latitud(first[0]):
                lat_c, lon_c = first[0], first[1]
            else:
                lon_c, lat_c = first[0], first[1]
            
            kml += f"\n              {lon_c},{lat_c},0"
            kml += '''
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>'''
        
        # Cerrar documento
        kml += '''
  </Document>
</kml>'''
        
        try:
            with open(kml_file, 'w', encoding='utf-8') as f:
                f.write(kml)
            print(f"  ✓ KML generado: {kml_file.name}")
            return True
        except Exception as e:
            print(f"  ✗ Error generando KML: {e}")
            return False
    
    def generar_informe_pdf(self, referencia):
        """Genera informe PDF si ReportLab está disponible"""
        if not REPORTLAB_AVAILABLE:
            return False
        
        ref = self.limpiar_referencia(referencia)
        pdf_file = self.output_dir / f"{ref}_informe.pdf"
        
        try:
            # Código simplificado de generación de PDF
            from reportlab.lib.pagesizes import A4
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet
            
            doc = SimpleDocTemplate(str(pdf_file), pagesize=A4)
            styles = getSampleStyleSheet()
            story = []

            # Título
            story.append(Paragraph(f"Informe Catastral - {ref}", styles['Title']))
            story.append(Spacer(1, 12))

            # Contenido básico
            story.append(Paragraph(f"Referencia: {ref}", styles['Normal']))
            story.append(Paragraph(f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
            story.append(Paragraph("Documentación descargada del Catastro", styles['Normal']))
            story.append(Spacer(1, 12))

            # Insertar ortofoto compuesta si existe
            try:
                # Intentar usar la versión con contorno primero
                comp_path = self.output_dir / f"{ref}_plano_con_ortofoto_contorno.png"
                if not comp_path.exists():
                    comp_path = self.output_dir / f"{ref}_plano_con_ortofoto.png"
                
                if comp_path.exists():
                    # Ajustar tamaño para A4 (márgenes ligeros)
                    from reportlab.lib.units import inch
                    max_width = A4[0] - 2 * cm
                    img = RLImage(str(comp_path))
                    iw, ih = img.wrap(0, 0)
                    scale = min(1.0, max_width / iw) if iw > 0 else 1.0
                    img.drawWidth = iw * scale
                    img.drawHeight = ih * scale
                    story.append(img)
                    story.append(Spacer(1, 12))
                    story.append(Paragraph("Detalle de Parcela (PNOA + Catastro)", styles['Italic']))
                    story.append(Spacer(1, 12))
                
                # Insertar ortofotos de contexto
                contextos = [
                    ("ortofoto_provincial", "Situación Provincial"),
                    ("ortofoto_autonomico", "Situación Autonómica"),
                    ("ortofoto_nacional", "Situación Nacional")
                ]
                
                story.append(Paragraph("Localización Territorial", styles['Heading3']))
                story.append(Spacer(1, 6))
                
                for suffix, titulo in contextos:
                    fname = f"{ref}_{suffix}.jpg"
                    path = self.output_dir / fname
                    if path.exists():
                        img = RLImage(str(path))
                        iw, ih = img.wrap(0, 0)
                        scale = min(1.0, (A4[0] - 2*cm) / iw) if iw > 0 else 1.0
                        img.drawWidth = iw * scale
                        img.drawHeight = ih * scale
                        story.append(Paragraph(titulo, styles['Normal']))
                        story.append(img)
                        story.append(Spacer(1, 10))

            except Exception as e:
                print(f"  ⚠ No se pudo insertar ortofoto en PDF: {e}")

            # Añadir lista de archivos generados (si existen)
            files_list = []
            for fname in [f"{ref}_plano_catastro.png", f"{ref}_ortofoto_pnoa.jpg", f"{ref}_plano_con_ortofoto.png", f"{ref}_consulta_oficial.pdf"]:
                p = self.output_dir / fname
                if p.exists():
                    files_list.append(fname)

            if files_list:
                story.append(Paragraph("Archivos generados:", styles['Heading3']))
                for f in files_list:
                    story.append(Paragraph(f"- {f}", styles['Normal']))
                story.append(Spacer(1, 12))

            doc.build(story)
            print(f"  ✓ Informe PDF generado: {pdf_file.name}")
            return True
            
        except Exception as e:
            print(f"  ⚠ Error generando PDF: {e}")
            return False
    
    def superponer_contorno_parcela(self, referencia, bbox_wgs84):
        """Superpone contorno en imágenes (requiere Pillow)"""
        if not PILLOW_AVAILABLE:
            return False
        
        ref = self.limpiar_referencia(referencia)
        gml_file = self.output_dir / f"{ref}_parcela.gml"
        
        if not gml_file.exists():
            return False
        
        anillos_poligono = self.extraer_coordenadas_gml(str(gml_file))
        if not anillos_poligono:
            return False
        
        # Lista de imágenes a procesar
        imagenes = [
            (f"{ref}_plano_catastro.png", f"{ref}_plano_catastro_contorno.png"),
            (f"{ref}_plano_con_ortofoto.png", f"{ref}_plano_con_ortofoto_contorno.png"),
            (f"{ref}_ortofoto_pnoa.jpg", f"{ref}_ortofoto_pnoa_contorno.jpg"),
        ]
        
        exitos = 0
        
        for img_in, img_out in imagenes:
            img_path = self.output_dir / img_in
            out_path = self.output_dir / img_out
            
            if not img_path.exists():
                continue
            
            try:
                # Abrir imagen
                with Image.open(img_path) as img:
                    img = img.convert("RGBA")
                    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
                    draw = ImageDraw.Draw(overlay)
                    
                    width, height = img.size
                    
                    # Convertir coordenadas a píxeles
                    coords_bbox = [float(x) for x in bbox_wgs84.split(",")]
                    minx, miny, maxx, maxy = coords_bbox
                    
                    for i, anillo in enumerate(anillos_poligono):
                        pixels_anillo = []
                        
                        for coord in anillo:
                            # Determinar lat/lon
                            if self._es_latitud(coord[0]):
                                lat, lon = coord[0], coord[1]
                            else:
                                lon, lat = coord[0], coord[1]
                            
                            # Normalizar a coordenadas de imagen
                            x = int(((lon - minx) / (maxx - minx)) * width)
                            y = int(((maxy - lat) / (maxy - miny)) * height)
                            
                            pixels_anillo.append((x, y))
                        
                        # Dibujar anillo si tiene suficientes puntos
                        if len(pixels_anillo) > 2:
                            # Relleno rojo semitransparente
                            draw.polygon(pixels_anillo, fill=(255, 0, 0, 60))
                            # Borde rojo sólido
                            draw.line(pixels_anillo + [pixels_anillo[0]], fill=(255, 0, 0, 255), width=3)
                            
                            print(f"    Anillo {i+1}: {len(pixels_anillo)} puntos dibujados")
                    
                    # Si los anillos son muy pequeños (vista nacional), dibujar puntos/círculos
                    total_puntos = sum(len(anillo) for anillo in anillos_poligono)
                    if total_puntos > 0:
                        # Calcular bounding box de todos los puntos
                        todos_puntos = []
                        for anillo in anillos_poligono:
                            for coord in anillo:
                                if self._es_latitud(coord[0]):
                                    lat, lon = coord[0], coord[1]
                                else:
                                    lon, lat = coord[0], coord[1]
                                
                                x = int(((lon - minx) / (maxx - minx)) * width)
                                y = int(((maxy - lat) / (maxy - miny)) * height)
                                todos_puntos.append((x, y))
                        
                        if todos_puntos:
                            xs = [p[0] for p in todos_puntos]
                            ys = [p[1] for p in todos_puntos]
                            w_px = max(xs) - min(xs)
                            h_px = max(ys) - min(ys)
                            
                            # Si es muy pequeño, dibujar círculos en centroides de anillos
                            if w_px < 15 and h_px < 15:
                                for i, anillo in enumerate(anillos_poligono):
                                    if len(anillo) > 0:
                                        # Calcular centroide del anillo
                                        anillo_pixels = []
                                        for coord in anillo:
                                            if self._es_latitud(coord[0]):
                                                lat, lon = coord[0], coord[1]
                                            else:
                                                lon, lat = coord[0], coord[1]
                                            
                                            x = int(((lon - minx) / (maxx - minx)) * width)
                                            y = int(((maxy - lat) / (maxy - miny)) * height)
                                            anillo_pixels.append((x, y))
                                        
                                        if anillo_pixels:
                                            cx = sum(p[0] for p in anillo_pixels) / len(anillo_pixels)
                                            cy = sum(p[1] for p in anillo_pixels) / len(anillo_pixels)
                                            r = 6
                                            draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(255, 0, 0, 255), outline=(255, 255, 255, 255))
                                            print(f"    Círculo anillo {i+1} en centroide ({cx}, {cy})")
                    
                    # Guardar imagen
                    result = Image.alpha_composite(img, overlay).convert("RGB")
                    result.save(out_path)
                    exitos += 1
                    print(f"  ✓ Contorno superpuesto en {img_out} ({len(anillos_poligono)} anillos)")
            
            except Exception as e:
                print(f"  ⚠ Error superponiendo {img_in}: {e}")
        
        return exitos > 0
    
    def crear_zip_referencia(self, referencia, directorio_base):
        """Crea ZIP con todos los archivos de la referencia"""
        ref = self.limpiar_referencia(referencia)
        dir_referencia = Path(directorio_base) / ref
        
        if not dir_referencia.exists():
            return None
        
        zip_file = Path(directorio_base) / f"{ref}_completo.zip"
        
        try:
            with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for archivo in dir_referencia.rglob('*'):
                    if archivo.is_file():
                        arcname = archivo.relative_to(directorio_base)
                        zipf.write(archivo, arcname)
            
            tamaño_mb = zip_file.stat().st_size / (1024 * 1024)
            print(f"  ✓ ZIP creado: {zip_file.name} ({tamaño_mb:.1f} MB)")
            return str(zip_file)
        
        except Exception as e:
            print(f"  ✗ Error creando ZIP: {e}")
            return None
    
    def _mostrar_resumen(self, resultados):
        """Muestra resumen del procesamiento"""
        if not resultados.get('exitosa'):
            return
        
        print(f"\n{'='*60}")
        print("📊 RESUMEN DEL PROCESAMIENTO")
        print(f"{'='*60}")
        
        ref = resultados.get('referencia', 'N/A')
        print(f"Referencia: {ref}")
        
        # Contar elementos exitosos
        elementos = [
            ('Coordenadas', 'coordenadas'),
            ('Parcela GML', 'parcela_gml'),
            ('Edificio GML', 'edificio_gml'),
            ('Plano catastral', 'plano_ortofoto'),
            ('PDF oficial', 'pdf_oficial'),
            ('Archivo KML', 'kml'),
            ('Capas afecciones', 'capas_afecciones'),
            ('Informe PDF', 'informe_pdf'),
            ('Contorno superpuesto', 'contorno_superpuesto'),
        ]
        
        exitosos = 0
        for nombre, clave in elementos:
            if resultados.get(clave):
                print(f"  ✓ {nombre}")
                exitosos += 1
            else:
                print(f"  ✗ {nombre}")
        
        print(f"\nTotal: {exitosos}/{len(elementos)} elementos completados")
        
        if 'zip_path' in resultados and resultados['zip_path']:
            print(f"\n📦 ZIP generado: {Path(resultados['zip_path']).name}")
        
        print(f"{'='*60}")


def procesar_y_comprimir(referencia, directorio_base="descargas_catastro",
                         organize_by_type=False, generate_pdf=True,
                         template_html=None, css_path=None,
                         descargar_afecciones=True):
    """
    Función principal para procesar una referencia.
    
    Args:
        referencia: Referencia catastral
        directorio_base: Directorio de salida
        organize_by_type: Organizar por tipo (futura implementación)
        generate_pdf: Generar informe PDF
        template_html: Plantilla HTML (futura implementación)
        css_path: Hoja de estilos CSS (futura implementación)
        descargar_afecciones: Descargar capas de afecciones
    
    Returns:
        (ruta_zip, resultados) o None
    """
    try:
        # Organizar por tipo si está habilitado
        if organize_by_type:
            subdirs = ['pdf', 'imagenes', 'geometrias', 'otros']
            for subdir in subdirs:
                (Path(directorio_base) / subdir).mkdir(exist_ok=True, parents=True)
        
        # Crear descargador
        downloader = CatastroDownloader(output_dir=directorio_base)
        
        # Procesar referencia
        resultados = downloader.descargar_todo(
            referencia=referencia,
            crear_zip=True,
            descargar_afecciones=descargar_afecciones
        )
        
        # Obtener ruta del ZIP
        zip_path = resultados.get('zip_path')
        
        if zip_path:
            print(f"\n✅ Proceso completado: {referencia}")
            print(f"📁 Archivos en: {directorio_base}/{referencia}")
            print(f"📦 ZIP: {zip_path}")
        
        return zip_path, resultados
    
    except Exception as e:
        print(f"❌ Error en procesar_y_comprimir: {e}")
        import traceback
        traceback.print_exc()
        return None


def procesar_lista_y_comprimir(lista_referencias, directorio_base="descargas_catastro",
                               organize_by_type=False, generate_pdf=True,
                               template_html=None, css_path=None,
                               descargar_afecciones=True):
    """
    Procesa múltiples referencias.
    
    Args:
        lista_referencias: Lista de referencias
        directorio_base: Directorio de salida
        organize_by_type: Organizar por tipo
        generate_pdf: Generar PDF
        template_html: Plantilla HTML
        css_path: Hoja de estilos
        descargar_afecciones: Descargar afecciones
    
    Returns:
        Ruta del ZIP de lote
    """
    try:
        print(f"\n📋 Iniciando procesamiento de lote ({len(lista_referencias)} referencias)")
        
        # Crear directorio base
        Path(directorio_base).mkdir(exist_ok=True)
        
        # Crear descargador
        downloader = CatastroDownloader(
            output_dir=directorio_base,
            max_workers=min(4, len(lista_referencias))
        )
        
        datos_resumen = []
        
        # Función de callback para mostrar progreso
        def callback_progreso(actual, total, ref, resultado):
            porcentaje = (actual / total) * 100
            print(f"  [{actual}/{total}] {ref} - {'✅' if resultado.get('exitosa') else '❌'}")
        
        # Procesar en paralelo
        resultados = downloader.descargar_paralelo(
            lista_referencias,
            callback=callback_progreso
        )
        
        # Recopilar datos para el resumen (Punto 5)
        for ref, resultado in resultados:
            info = {
                "Referencia": ref,
                "Estado": "Correcto" if resultado.get('exitosa') else "Error",
                "Error": resultado.get('error', ''),
                "Provincia": "", "Municipio": "", 
                "Latitud": "", "Longitud": "", "UTM_X": "", "UTM_Y": "", "Huso": "",
                "Superficie_Catastro_m2": "", "Superficie_Construida_m2": "",
                "Año_Construccion": "", "Uso_Principal": ""
            }
            
            if resultado.get('exitosa'):
                # Datos Geográficos
                coords = resultado.get('coordenadas', {})
                if coords:
                    lat, lon = coords.get('lat'), coords.get('lon')
                    info["Latitud"] = lat
                    info["Longitud"] = lon
                    x, y, huso = downloader.convertir_a_utm(lon, lat)
                    info["UTM_X"] = f"{x:.2f}"
                    info["UTM_Y"] = f"{y:.2f}"
                    info["Huso"] = huso
                
                # Datos Alfanuméricos (intentar obtener si no están en resultado)
                # Nota: descargar_todo no devuelve los datos XML explícitamente en el dict principal por defecto,
                # así que hacemos una llamada rápida al XML aquí si es necesario o extraemos de lo que tengamos.
                # Para eficiencia, idealmente descargar_todo debería devolverlos. 
                # Hacemos una llamada rápida aquí:
                datos_xml = downloader.obtener_datos_alfanumericos(ref)
                if datos_xml:
                    # Extraer Provincia/Municipio del domicilio si es posible o del código
                    # El XML de DNPRC no siempre trae códigos limpios, usamos el domicilio
                    domicilio = datos_xml.get('domicilio', '')
                    parts = domicilio.split('(')
                    if len(parts) > 1:
                        info["Municipio"] = parts[-1].replace(')', '').strip()
                    
                    info["Superficie_Construida_m2"] = datos_xml.get('superficie_construida', 0)
                    info["Año_Construccion"] = datos_xml.get('anio_construccion', '')
                    info["Uso_Principal"] = datos_xml.get('uso_principal', '')
                    
                    # Superficie suelo (aprox desde bienes o GML si se analizara)
                    # Aquí usamos la construida como proxy si no hay otra
            
            datos_resumen.append(info)

        # Crear ZIP de lote
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_lote = Path(directorio_base) / f"lote_{timestamp}_{len(lista_referencias)}_refs.zip"
        
        with zipfile.ZipFile(zip_lote, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # 1. Añadir Resumen CSV al ZIP
            csv_buffer = BytesIO()
            if datos_resumen:
                fieldnames = datos_resumen[0].keys()
                writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames, delimiter=';') # Excel friendly
                writer.writeheader()
                writer.writerows(datos_resumen)
                zipf.writestr(f"resumen_lote_{timestamp}.csv", csv_buffer.getvalue().decode('utf-8'))
            
            # 2. Añadir archivos descargados
            for ref, resultado in resultados:
                if resultado.get('exitosa'):
                    dir_ref = Path(directorio_base) / ref
                    if dir_ref.exists():
                        for archivo in dir_ref.rglob('*'):
                            if archivo.is_file():
                                arcname = archivo.relative_to(directorio_base)
                                zipf.write(archivo, arcname)
        
        tamaño_mb = zip_lote.stat().st_size / (1024 * 1024)
        print(f"\n✅ Lote completado")
        print(f"📦 ZIP de lote: {zip_lote.name} ({tamaño_mb:.1f} MB)")
        
        # Resumen
        exitosas = sum(1 for _, r in resultados if r.get('exitosa'))
        print(f"📊 Resultados: {exitosas}/{len(lista_referencias)} exitosas")
        
        return str(zip_lote)
    
    except Exception as e:
        print(f"❌ Error en procesar_lista_y_comprimir: {e}")
        import traceback
        traceback.print_exc()
        return None


# Ejemplo de uso
if __name__ == "__main__":
    print("=" * 60)
    print("DESCARGADOR CATASTRAL OPTIMIZADO v2.0")
    print("=" * 60)
    print()
    
    # Configuración
    import argparse
    parser = argparse.ArgumentParser(description='Descargador catastral')
    parser.add_argument('--referencia', help='Referencia catastral')
    parser.add_argument('--archivo', help='Archivo con lista de referencias')
    parser.add_argument('--output', help='Directorio de salida', default='descargas_catastro')
    parser.add_argument('--cache', help='Horas de cache HTTP', type=int, default=1)
    
    args = parser.parse_args()
    
    if args.referencia:
        # Procesar referencia única
        zip_path, resultados = procesar_y_comprimir(
            referencia=args.referencia,
            directorio_base=args.output
        )
        
        if zip_path:
            print(f"\n✅ ZIP disponible: {zip_path}")
    
    elif args.archivo and os.path.exists(args.archivo):
        # Procesar lista
        with open(args.archivo, 'r', encoding='utf-8') as f:
            referencias = [line.strip() for line in f if line.strip()]
        
        if referencias:
            zip_lote = procesar_lista_y_comprimir(
                lista_referencias=referencias,
                directorio_base=args.output
            )
            
            if zip_lote:
                print(f"\n✅ ZIP de lote: {zip_lote}")
    
    else:
        print("Modo interactivo")
        print("\nEjemplos de uso:")
        print("  python catastro4.py --referencia 30037A008002060000UZ")
        print("  python catastro4.py --archivo referencias.txt")
        print("\nO ejecute main.py para la interfaz gráfica")
    
    print(f"\n📁 Directorio de salida: {args.output}")
