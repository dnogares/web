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
            
            # 8. Descargar PDF oficial
            pdf_descargado = self.descargar_consulta_descriptiva_pdf(ref)
            resultados['pdf_oficial'] = pdf_descargado
            
            # 9. Descargar capas de afecciones (si está habilitado)
            if descargar_afecciones and bbox:
                afecciones = self.descargar_capas_afecciones(ref, bbox)
                resultados['capas_afecciones'] = afecciones
            
            # 10. Generar informe PDF (si ReportLab está disponible)
            if REPORTLAB_AVAILABLE:
                try:
                    informe_generado = self.generar_informe_pdf(ref)
                    resultados['informe_pdf'] = informe_generado
                except Exception as e:
                    print(f"  ⚠ Error generando informe PDF: {e}")
                    resultados['informe_pdf'] = False
            
            # 11. Superponer contornos en TODAS las imágenes
            if PILLOW_AVAILABLE and coords_poligono and bbox:
                print(f"  🎨 Aplicando siluetas a todas las imágenes...")
                
                # Primero usar la función específica para imágenes conocidas
                contorno_superpuesto = self.superponer_contorno_parcela(ref, bbox)
                resultados['contorno_superpuesto'] = contorno_superpuesto
                
                # Luego aplicar a TODAS las imágenes encontradas
                contorno_completo = self.superponer_contorno_en_todas_imagenes(ref, bbox)
                resultados['contorno_completo'] = contorno_completo
                
                if contorno_completo:
                    print(f"  ✅ Siluetas aplicadas a todas las imágenes disponibles")
                else:
                    print(f"  ⚠ No se encontraron imágenes adicionales para procesar")
                
                # 12. APLICAR SILUETAS A IMÁGENES ESPECÍFICAS PARA PDFs
                try:
                    self._aplicar_siluetas_imagenes_pdf(ref, coords_poligono, bbox)
                    resultados['siluetas_pdf'] = True
                    print(f"  ✅ Siluetas aplicadas a imágenes para PDFs")
                except Exception as pdf_sil_e:
                    print(f"  ⚠ Error aplicando siluetas a PDFs: {pdf_sil_e}")
                    resultados['siluetas_pdf'] = False
                
                # 13. Crear composiciones GML + capas de intersección
                try:
                    composiciones_gml = self.crear_composicion_gml_intersecciones(ref, bbox)
                    resultados['composiciones_gml'] = composiciones_gml
                    
                    if composiciones_gml:
                        print(f"  ✅ Composiciones GML + intersecciones generadas")
                    else:
                        print(f"  ⚠ No se generaron composiciones GML")
                        
                except Exception as comp_e:
                    print(f"  ⚠ Error generando composiciones GML: {comp_e}")
                    resultados['composiciones_gml'] = False
            
            # 13. Crear ZIP si se solicita
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
                "WIDTH": "1600",
                "HEIGHT": "1600",
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
                "WIDTH": "1600",
                "HEIGHT": "1600",
                "FORMAT": "image/jpeg",
            }
            
            response = self.session.get(self.base_urls['ign_pnoa'], params=params, timeout=60)
            
            if response.status_code == 200 and len(response.content) > 5000:
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
                                # Asegurar mismo tamaño
                                img_orto = img_orto.resize(img_plano.size)
                                
                                # Crear composición (60% ortofoto, 40% plano)
                                composicion = Image.blend(
                                    img_orto.convert("RGBA"),
                                    img_plano.convert("RGBA"),
                                    alpha=0.4
                                )
                                
                                comp_file = self.output_dir / f"{ref}_plano_con_ortofoto.png"
                                composicion.save(comp_file, "PNG")
                                print(f"  ✓ Composición creada")
                                
                                # INMEDIATAMENTE aplicar silueta a la composición
                                if coords_poligono and bbox_wgs84:
                                    try:
                                        # Convertir coordenadas a píxeles para la composición
                                        coords_bbox = [float(x) for x in bbox_wgs84.split(",")]
                                        minx, miny, maxx, maxy = coords_bbox
                                        width, height = composicion.size
                                        
                                        pixels = []
                                        for coord in coords_poligono:
                                            if self._es_latitud(coord[0]):
                                                lat, lon = coord[0], coord[1]
                                            else:
                                                lon, lat = coord[0], coord[1]
                                            
                                            x = int(((lon - minx) / (maxx - minx)) * width)
                                            y = int(((maxy - lat) / (maxy - miny)) * height)
                                            pixels.append((x, y))
                                        
                                        # Dibujar silueta en la composición
                                        if len(pixels) > 2:
                                            overlay = Image.new('RGBA', composicion.size, (0, 0, 0, 0))
                                            draw = ImageDraw.Draw(overlay)
                                            
                                            # Línea principal (roja brillante)
                                            draw.line(pixels + [pixels[0]], fill=(255, 0, 0), width=4)
                                            # Línea secundaria (blanca) para contraste
                                            draw.line(pixels + [pixels[0]], fill=(255, 255, 255), width=2)
                                            
                                            composicion_con_contorno = Image.alpha_composite(composicion, overlay)
                                            comp_contorno_file = self.output_dir / f"{ref}_plano_con_ortofoto_contorno.png"
                                            composicion_con_contorno.convert('RGB').save(comp_contorno_file, quality=95)
                                            print(f"  ✓ Silueta aplicada a composición")
                                    except Exception as contour_e:
                                        print(f"  ⚠ Error aplicando silueta a composición: {contour_e}")
                    
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
        """Extrae coordenadas de archivo GML"""
        try:
            tree = ET.parse(gml_file)
            root = tree.getroot()
            
            coords = []
            namespaces = {'gml': 'http://www.opengis.net/gml/3.2'}
            
            # Buscar posList
            for pos_list in root.findall('.//gml:posList', namespaces):
                if pos_list.text:
                    partes = pos_list.text.strip().split()
                    for i in range(0, len(partes), 2):
                        if i + 1 < len(partes):
                            coords.append((float(partes[i]), float(partes[i+1])))
            
            # Si no hay posList, buscar pos
            if not coords:
                for pos in root.findall('.//gml:pos', namespaces):
                    if pos.text:
                        partes = pos.text.strip().split()
                        if len(partes) >= 2:
                            coords.append((float(partes[0]), float(partes[1])))
            
            if coords:
                return coords
            
        except Exception as e:
            print(f"  ⚠ Error extrayendo coordenadas GML: {e}")
        
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
        
        coords_poligono = self.extraer_coordenadas_gml(str(gml_file))
        if not coords_poligono:
            return False
        
        # Lista de imágenes a procesar - AMPLIADA para incluir TODOS los tipos posibles
        imagenes = [
            # Imágenes principales
            (f"{ref}_plano_catastro.png", f"{ref}_plano_catastro_contorno.png"),
            (f"{ref}_plano_con_ortofoto.png", f"{ref}_plano_con_ortofoto_contorno.png"),
            (f"{ref}_ortofoto_pnoa.jpg", f"{ref}_ortofoto_pnoa_contorno.jpg"),
            
            # Imágenes de afecciones
            (f"{ref}_afeccion_hidrografia.png", f"{ref}_afeccion_hidrografia_contorno.png"),
            (f"{ref}_afeccion_planeamiento.png", f"{ref}_afeccion_planeamiento_contorno.png"),
            (f"{ref}_afeccion_catastro_parcelas.png", f"{ref}_afeccion_catastro_parcelas_contorno.png"),
            (f"{ref}_afeccion_otros.png", f"{ref}_afeccion_otros_contorno.png"),
            
            # Imágenes de análisis urbanístico
            (f"{ref}_analisis_urbanistico.png", f"{ref}_analisis_urbanistico_contorno.png"),
            (f"{ref}_uso_suelo.png", f"{ref}_uso_suelo_contorno.png"),
            (f"{ref}_calificacion_urbanistica.png", f"{ref}_calificacion_urbanistica_contorno.png"),
            
            # Imágenes de escalas múltiples
            (f"{ref}_plano_catastro_1.0.png", f"{ref}_plano_catastro_1.0_contorno.png"),
            (f"{ref}_plano_catastro_0.5.png", f"{ref}_plano_catastro_0.5_contorno.png"),
            (f"{ref}_plano_catastro_2.0.png", f"{ref}_plano_catastro_2.0_contorno.png"),
            (f"{ref}_ortofoto_pnoa_1.0.jpg", f"{ref}_ortofoto_pnoa_1.0_contorno.jpg"),
            (f"{ref}_ortofoto_pnoa_0.5.jpg", f"{ref}_ortofoto_pnoa_0.5_contorno.jpg"),
            (f"{ref}_ortofoto_pnoa_2.0.jpg", f"{ref}_ortofoto_pnoa_2.0_contorno.jpg"),
            
            # Imágenes combinadas con buffer
            (f"{ref}_plano_con_buffer.png", f"{ref}_plano_con_buffer_contorno.png"),
            (f"{ref}_ortofoto_con_buffer.png", f"{ref}_ortofoto_con_buffer_contorno.png"),
            
            # Imágenes de informes y documentos
            (f"{ref}_mapa_situacion.png", f"{ref}_mapa_situacion_contorno.png"),
            (f"{ref}_mapa_emplazamiento.png", f"{ref}_mapa_emplazamiento_contorno.png"),
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
                    width, height = img.size
                    
                    # Convertir coordenadas a píxeles
                    coords_bbox = [float(x) for x in bbox_wgs84.split(",")]
                    minx, miny, maxx, maxy = coords_bbox
                    
                    pixels = []
                    for coord in coords_poligono:
                        # Determinar lat/lon
                        if self._es_latitud(coord[0]):
                            lat, lon = coord[0], coord[1]
                        else:
                            lon, lat = coord[0], coord[1]
                        
                        # Normalizar a coordenadas de imagen
                        x = int(((lon - minx) / (maxx - minx)) * width)
                        y = int(((maxy - lat) / (maxy - miny)) * height)
                        
                        pixels.append((x, y))
                    
                    # Dibujar contorno con mejor visibilidad y estilo
                    if len(pixels) > 2:
                        # Crear capa de dibujo con transparencia
                        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
                        draw = ImageDraw.Draw(overlay)
                        
                        # Dibujar línea principal (roja brillante)
                        draw.line(pixels + [pixels[0]], fill=(255, 0, 0), width=4)
                        
                        # Dibujar línea secundaria (blanca) para mejor contraste
                        draw.line(pixels + [pixels[0]], fill=(255, 255, 255), width=2)
                        
                        # Combinar con imagen original
                        img_with_contour = Image.alpha_composite(img.convert('RGBA'), overlay)
                        
                        # Guardar como PNG para mantener calidad
                        final_output = out_path.with_suffix('.png') if out_path.suffix.lower() == '.jpg' else out_path
                        img_with_contour.convert('RGB').save(final_output, quality=95)
                        
                        # Si el archivo original era JPG y creamos PNG, también guardar versión JPG
                        if out_path.suffix.lower() == '.jpg' and final_output.suffix.lower() == '.png':
                            img_with_contour.convert('RGB').save(out_path, quality=90)
                        
                        exitos += 1
                        print(f"  ✓ Contorno superpuesto en {img_in}")
            
            except Exception as e:
                print(f"  ⚠ Error superponiendo {img_in}: {e}")
        
        return exitos > 0
    
    def superponer_contorno_en_todas_imagenes(self, referencia, bbox_wgs84):
        """Superpone contorno en TODAS las imágenes encontradas en el directorio"""
        ref = self.limpiar_referencia(referencia)
        gml_file = self.output_dir / f"{ref}_parcela.gml"
        
        if not gml_file.exists():
            return False
        
        coords_poligono = self.extraer_coordenadas_gml(str(gml_file))
        if not coords_poligono:
            return False
        
        # Buscar TODAS las imágenes en el directorio de la referencia
        ref_dir = self.output_dir
        image_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff']
        imagenes_encontradas = []
        
        for ext in image_extensions:
            for img_path in ref_dir.glob(f"{ref}*{ext}"):
                # Ignorar archivos que ya tienen contorno
                if '_contorno' not in img_path.name:
                    # Generar nombre de archivo con contorno
                    if ext.lower() in ['.jpg', '.jpeg']:
                        out_name = img_path.stem + '_contorno.jpg'
                    else:
                        out_name = img_path.stem + '_contorno.png'
                    out_path = img_path.parent / out_name
                    imagenes_encontradas.append((img_path, out_path))
        
        if not imagenes_encontradas:
            print(f"  ⚠ No se encontraron imágenes para procesar")
            return False
        
        print(f"  📸 Procesando {len(imagenes_encontradas)} imágenes encontradas...")
        
        # Procesar cada imagen encontrada
        exitos = 0
        coords_bbox = [float(x) for x in bbox_wgs84.split(",")]
        minx, miny, maxx, maxy = coords_bbox
        
        for img_path, out_path in imagenes_encontradas:
            try:
                with Image.open(img_path) as img:
                    width, height = img.size
                    
                    # Convertir coordenadas a píxeles
                    pixels = []
                    for coord in coords_poligono:
                        if self._es_latitud(coord[0]):
                            lat, lon = coord[0], coord[1]
                        else:
                            lon, lat = coord[0], coord[1]
                        
                        x = int(((lon - minx) / (maxx - minx)) * width)
                        y = int(((maxy - lat) / (maxy - miny)) * height)
                        pixels.append((x, y))
                    
                    # Dibujar contorno con mejor visibilidad
                    if len(pixels) > 2:
                        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
                        draw = ImageDraw.Draw(overlay)
                        
                        # Línea principal (roja brillante)
                        draw.line(pixels + [pixels[0]], fill=(255, 0, 0), width=4)
                        # Línea secundaria (blanca) para contraste
                        draw.line(pixels + [pixels[0]], fill=(255, 255, 255), width=2)
                        
                        img_with_contour = Image.alpha_composite(img.convert('RGBA'), overlay)
                        img_with_contour.convert('RGB').save(out_path, quality=95)
                        
                        exitos += 1
                        print(f"    ✓ Contorno en {img_path.name}")
            
            except Exception as e:
                print(f"    ⚠ Error procesando {img_path.name}: {e}")
        
        print(f"  ✅ Contornos superpuestos en {exitos}/{len(imagenes_encontradas)} imágenes")
        return exitos > 0
    
    def _aplicar_siluetas_imagenes_pdf(self, ref, coords_poligono, bbox_wgs84):
        """Aplica siluetas a imágenes específicas que se usan en PDFs"""
        ref = self.limpiar_referencia(ref)
        
        # Imágenes específicas que deben tener silueta para PDFs
        imagenes_pdf = [
            f"{ref}_plano_catastro.png",
            f"{ref}_ortofoto_pnoa.jpg", 
            f"{ref}_plano_con_ortofoto.png",
            f"{ref}_plano_con_ortofoto_contorno.png",
            f"{ref}_mapa_satelite.jpg",
            f"{ref}_mapa_calles.jpg"
        ]
        
        exitos = 0
        
        for img_name in imagenes_pdf:
            img_path = self.output_dir / img_name
            
            if img_path.exists():
                try:
                    # Solo aplicar si no tiene ya contorno
                    if "_contorno" not in img_name:
                        output_name = img_name.replace(".", "_contorno.")
                        output_path = self.output_dir / output_name
                        
                        if not output_path.exists():
                            # Aplicar silueta
                            with Image.open(img_path) as img:
                                width, height = img.size
                                
                                # Convertir coordenadas a píxeles
                                coords_bbox = [float(x) for x in bbox_wgs84.split(",")]
                                minx, miny, maxx, maxy = coords_bbox
                                
                                pixels = []
                                for coord in coords_poligono:
                                    for ring_coord in coord if isinstance(coord[0], (list, tuple)) else [coord]:
                                        if self._es_latitud(ring_coord[0]):
                                            lat, lon = ring_coord[0], ring_coord[1]
                                        else:
                                            lon, lat = ring_coord[0], ring_coord[1]
                                        
                                        x = int(((lon - minx) / (maxx - minx)) * width)
                                        y = int(((maxy - lat) / (maxy - miny)) * height)
                                        pixels.append((x, y))
                                
                                # Dibujar silueta
                                if len(pixels) > 2:
                                    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
                                    draw = ImageDraw.Draw(overlay)
                                    
                                    # Línea principal (roja brillante)
                                    draw.line(pixels + [pixels[0]], fill=(255, 0, 0), width=4)
                                    # Línea secundaria (blanca) para contraste
                                    draw.line(pixels + [pixels[0]], fill=(255, 255, 255), width=2)
                                    
                                    img_with_contour = Image.alpha_composite(img.convert('RGBA'), overlay)
                                    img_with_contour.convert('RGB').save(output_path, quality=95)
                                    
                                    print(f"    ✓ Silueta aplicada a {img_name}")
                                    exitos += 1
                    
                except Exception as e:
                    print(f"    ⚠ Error aplicando silueta a {img_name}: {e}")
        
        return exitos > 0
    
    def crear_composicion_gml_intersecciones(self, referencia, bbox_wgs84, capas_interseccion=None):
        """Crea composiciones visuales del GML con capas de intersección"""
        if not PILLOW_AVAILABLE:
            print("  ⚠ Pillow no disponible, no se pueden crear composiciones")
            return False
        
        ref = self.limpiar_referencia(referencia)
        gml_file = self.output_dir / f"{ref}_parcela.gml"
        
        if not gml_file.exists():
            print("  ⚠ No existe GML de parcela")
            return False
        
        coords_poligono = self.extraer_coordenadas_gml(str(gml_file))
        if not coords_poligono:
            print("  ⚠ No se pudieron extraer coordenadas del GML")
            return False
        
        # Si no se proporcionan capas, buscar automáticamente
        if capas_interseccion is None:
            capas_interseccion = self._buscar_capas_interseccion(ref)
        
        if not capas_interseccion:
            print("  ⚠ No se encontraron capas de intersección")
            return False
        
        print(f"  🎨 Creando composiciones con {len(capas_interseccion)} capas...")
        
        exitos = 0
        
        # Para cada capa de intersección, crear una composición
        for capa in capas_interseccion:
            try:
                # Buscar imagen de la capa de intersección
                imagen_capa = self._buscar_imagen_capa(ref, capa)
                if not imagen_capa:
                    print(f"    ⚠ No se encontró imagen para la capa: {capa}")
                    continue
                
                # Crear composición
                resultado = self._crear_composicion_individual(
                    ref, coords_poligono, bbox_wgs84, 
                    imagen_capa, capa
                )
                
                if resultado:
                    exitos += 1
                    print(f"    ✓ Composición creada: {capa}")
                
            except Exception as e:
                print(f"    ⚠ Error creando composición con {capa}: {e}")
        
        print(f"  ✅ Composiciones creadas: {exitos}/{len(capas_interseccion)}")
        return exitos > 0
    
    def _buscar_capas_interseccion(self, ref):
        """Busca capas con las que la referencia tiene intersección"""
        capas_encontradas = []
        
        # Buscar archivos de afecciones generados
        ref_dir = self.output_dir
        for archivo in ref_dir.glob(f"{ref}_afeccion_*.png"):
            nombre_capa = archivo.stem.replace(f"{ref}_afeccion_", "")
            capas_encontradas.append(nombre_capa)
        
        # Buscar en resultados de análisis
        csv_resultados = ref_dir / f"{ref}_afecciones.csv"
        if csv_resultados.exists():
            try:
                import pandas as pd
                df = pd.read_csv(csv_resultados)
                if 'capa' in df.columns:
                    capas_csv = df['capa'].unique().tolist()
                    capas_encontradas.extend(capas_csv)
            except Exception as e:
                print(f"    ⚠ Error leyendo CSV de afecciones: {e}")
        
        return list(set(capas_encontradas))  # Eliminar duplicados
    
    def _buscar_imagen_capa(self, ref, nombre_capa):
        """Busca la imagen de una capa específica"""
        ref_dir = self.output_dir
        
        # Posibles nombres de archivo
        posibles_nombres = [
            f"{ref}_afeccion_{nombre_capa}.png",
            f"{ref}_afeccion_{nombre_capa}.jpg",
            f"{ref}_{nombre_capa}.png",
            f"{ref}_{nombre_capa}.jpg",
            f"mapa_{nombre_capa}.jpg",
            f"silueta_{nombre_capa}.jpg"
        ]
        
        for nombre in posibles_nombres:
            archivo = ref_dir / nombre
            if archivo.exists():
                return archivo
        
        return None
    
    def _crear_composicion_individual(self, ref, coords_poligono, bbox_wgs84, imagen_capa, nombre_capa):
        """Crea una composición individual del GML con una capa específica con estilo mejorado"""
        try:
            # Abrir imagen de la capa
            with Image.open(imagen_capa) as img_capa:
                # Convertir a RGBA si es necesario
                if img_capa.mode != 'RGBA':
                    img_capa = img_capa.convert('RGBA')
                
                # Crear capa de dibujo para el GML
                overlay = Image.new('RGBA', img_capa.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(overlay)
                
                # Convertir coordenadas GML a píxeles
                coords_bbox = [float(x) for x in bbox_wgs84.split(",")]
                minx, miny, maxx, maxy = coords_bbox
                width, height = img_capa.size
                
                pixels = []
                for coord in coords_poligono:
                    for ring_coord in coord if isinstance(coord[0], (list, tuple)) else [coord]:
                        if self._es_latitud(ring_coord[0]):
                            lat, lon = ring_coord[0], ring_coord[1]
                        else:
                            lon, lat = ring_coord[0], ring_coord[1]
                        
                        x = int(((lon - minx) / (maxx - minx)) * width)
                        y = int(((maxy - lat) / (maxy - miny)) * height)
                        pixels.append((x, y))
                
                # Dibujar GML con estilo destacado y profesional
                if len(pixels) > 2:
                    fill_pixels = pixels + [pixels[0]]
                    
                    # 1. Relleno semitransparente para mejor visibilidad
                    try:
                        # Crear máscara para relleno
                        mask = Image.new('L', img_capa.size, 0)
                        draw_mask = ImageDraw.Draw(mask)
                        draw_mask.polygon(fill_pixels, fill=128)  # Semi-transparente
                        
                        # Capa de relleno rojo semitransparente
                        fill_layer = Image.new('RGBA', img_capa.size, (255, 0, 0, 60))
                        overlay.paste(fill_layer, (0, 0), mask)
                    except:
                        pass  # Si falla el relleno, continuar con bordes
                    
                    # 2. Borde múltiple para máxima visibilidad
                    # Borde exterior blanco (más grueso)
                    draw.line(fill_pixels, fill=(255, 255, 255), width=6)
                    # Borde principal rojo brillante
                    draw.line(fill_pixels, fill=(255, 0, 0), width=4)
                    # Borde interior blanco para contraste
                    draw.line(fill_pixels, fill=(255, 255, 255), width=2)
                    # Borde central rojo oscuro
                    draw.line(fill_pixels, fill=(200, 0, 0), width=1)
                
                # Añadir leyenda y título
                try:
                    from PIL import ImageFont
                    # Intentar cargar fuente, si no disponible usar fuente por defecto
                    try:
                        font_title = ImageFont.truetype("arial.ttf", 24)
                        font_legend = ImageFont.truetype("arial.ttf", 16)
                    except:
                        font_title = ImageFont.load_default()
                        font_legend = ImageFont.load_default()
                    
                    # Crear capa para texto
                    text_overlay = Image.new('RGBA', img_capa.size, (0, 0, 0, 0))
                    text_draw = ImageDraw.Draw(text_overlay)
                    
                    # Título con fondo semitransparente
                    title_text = f"Composición: {ref}"
                    title_bbox = text_draw.textbbox((10, 10), title_text, font=font_title)
                    title_width = title_bbox[2] - title_bbox[0]
                    title_height = title_bbox[3] - title_bbox[1]
                    
                    # Fondo para título
                    text_draw.rectangle([5, 5, title_width + 15, title_height + 15], 
                                      fill=(0, 0, 0, 180))
                    text_draw.text((10, 10), title_text, fill=(255, 255, 255), font=font_title)
                    
                    # Leyenda de la capa
                    capa_text = f"Capa: {nombre_capa}"
                    capa_bbox = text_draw.textbbox((10, 40), capa_text, font=font_legend)
                    capa_width = capa_bbox[2] - capa_bbox[0]
                    capa_height = capa_bbox[3] - capa_bbox[1]
                    
                    # Fondo para leyenda
                    text_draw.rectangle([5, 35, capa_width + 15, 35 + capa_height + 10], 
                                      fill=(0, 0, 0, 180))
                    text_draw.text((10, 40), capa_text, fill=(255, 255, 100), font=font_legend)
                    
                    # Leyenda de la parcela
                    parcela_text = "■ Parcela Catastral"
                    parcela_bbox = text_draw.textbbox((10, 65), parcela_text, font=font_legend)
                    
                    # Fondo para leyenda de parcela
                    text_draw.rectangle([5, 60, parcela_bbox[2] + 15, 60 + parcela_bbox[3] + 10], 
                                      fill=(255, 0, 0, 180))
                    text_draw.text((10, 65), parcela_text, fill=(255, 255, 255), font=font_legend)
                    
                    # Combinar con overlay principal
                    overlay = Image.alpha_composite(overlay, text_overlay)
                    
                except Exception as text_e:
                    print(f"      ⚠ Error añadiendo texto/leyenda: {text_e}")
                
                # Combinar imágenes
                composicion = Image.alpha_composite(img_capa, overlay)
                
                # Guardar composición con alta calidad
                safe_name = str(nombre_capa).replace("/", "_").replace("\\", "_").replace(":", "_")
                comp_file = self.output_dir / f"{ref}_composicion_gml_{safe_name}.png"
                composicion.convert('RGB').save(comp_file, quality=95)
                
                # También crear versión con marca de agua
                try:
                    watermark = Image.new('RGBA', composicion.size, (0, 0, 0, 0))
                    wm_draw = ImageDraw.Draw(watermark)
                    
                    # Marca de agua sutil
                    wm_text = "Generado por Catastro GIS"
                    try:
                        wm_font = ImageFont.truetype("arial.ttf", 12)
                    except:
                        wm_font = ImageFont.load_default()
                    
                    # Posición en la esquina inferior derecha
                    wm_bbox = wm_draw.textbbox((0, 0), wm_text, font=wm_font)
                    wm_width = wm_bbox[2] - wm_bbox[0]
                    wm_height = wm_bbox[3] - wm_bbox[1]
                    
                    pos_x = composicion.width - wm_width - 10
                    pos_y = composicion.height - wm_height - 10
                    
                    wm_draw.text((pos_x, pos_y), wm_text, fill=(255, 255, 255, 100), font=wm_font)
                    
                    # Aplicar marca de agua
                    composicion_con_wm = Image.alpha_composite(composicion.convert('RGBA'), watermark)
                    composicion_con_wm.convert('RGB').save(comp_file, quality=95)
                    
                except Exception as wm_e:
                    print(f"      ⚠ Error añadiendo marca de agua: {wm_e}")
                
                return True
                
        except Exception as e:
            print(f"      ⚠ Error en composición individual: {e}")
            return False
    
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
        
        # Función de callback para mostrar progreso
        def callback_progreso(actual, total, ref, resultado):
            porcentaje = (actual / total) * 100
            print(f"  [{actual}/{total}] {ref} - {'✅' if resultado.get('exitosa') else '❌'}")
        
        # Procesar en paralelo
        resultados = downloader.descargar_paralelo(
            lista_referencias,
            callback=callback_progreso
        )
        
        # Crear ZIP de lote
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_lote = Path(directorio_base) / f"lote_{timestamp}_{len(lista_referencias)}_refs.zip"
        
        with zipfile.ZipFile(zip_lote, 'w', zipfile.ZIP_DEFLATED) as zipf:
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
