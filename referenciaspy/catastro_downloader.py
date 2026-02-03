from pathlib import Path
import os
import time

import json
import zipfile
import requests
import logging
from io import BytesIO
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Any, Tuple
import numpy as np
from shapely.geometry import shape, Polygon, MultiPolygon, Point
from shapely.ops import transform
from pyproj import Transformer

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Dependencias opcionales
try:
    import geopandas as gpd
    import matplotlib.pyplot as plt
    import contextily as cx
    from shapely.geometry import mapping, Point
    from PIL import Image, ImageDraw, ImageFont
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    GEOTOOLS_AVAILABLE = True
    PILLOW_AVAILABLE = True
except ImportError:
    logger.warning("Faltan dependencias (geopandas, matplotlib, pillow, contextily). Funcionalidad limitada.")
    GEOTOOLS_AVAILABLE = False
    PILLOW_AVAILABLE = False

def safe_get(url, params=None, headers=None, timeout=30, max_retries=2, method='get', json_body=None):
    """Wrapper con reintentos para requests"""
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            if method.lower() == 'get':
                r = requests.get(url, params=params, headers=headers, timeout=timeout)
            else:
                r = requests.post(url, params=params, headers=headers, json=json_body, timeout=timeout)
            return r
        except requests.exceptions.RequestException as e:
            last_exc = e
            time.sleep(1 + attempt)
    raise last_exc

class CatastroDownloader:
    """
    Descarga documentación del Catastro español a partir de referencias catastrales.
    Incluye generación de mapas con ortofoto usando servicios WMS y superposición de contorno.
    """

    def __init__(self, output_dir="descargas_catastro"):
        self.output_dir = Path(output_dir)
        self.base_url = "https://ovc.catastro.meh.es"
        self.output_dir.mkdir(exist_ok=True)
        # Diccionario auxiliar para los códigos de municipio/delegación. 
        # Es necesario para descargar la consulta oficial
        self._municipio_cache = {} 


    def limpiar_referencia(self, ref):
        """Limpia la referencia catastral eliminando espacios."""
        return ref.replace(" ", "").strip()

    def extraer_del_mun(self, ref):
        """Extrae el código de delegación (2 dígitos) y municipio (3 dígitos) de la referencia."""
        ref = self.limpiar_referencia(ref)
        if len(ref) >= 5:
            # El Catastro usa los 5 primeros dígitos para delegación/municipio
            return ref[:2], ref[2:5] # C=provincia (2), M=municipio (3)
        return "", ""

    def obtener_coordenadas_unificado(self, referencia):
        """Obtiene coordenadas unificadas usando el método estándar"""
        return self.obtener_coordenadas(referencia)

    def obtener_coordenadas(self, referencia):
        """Obtiene las coordenadas de la parcela desde el servicio del Catastro."""
        ref = self.limpiar_referencia(referencia)

        # Método 1: Servicio REST JSON
        try:
            url_json = (
                "https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/"
                f"COVCCallejero.svc/json/Geo_RCToWGS84/{ref}"
            )
            response = safe_get(url_json, timeout=30)

            if response.status_code == 200:
                data = response.json()
                if (
                    "geo" in data
                    and "xcen" in data["geo"]
                    and "ycen" in data["geo"]
                ):
                    lon = float(data["geo"]["xcen"])
                    lat = float(data["geo"]["ycen"])
                    print(f"  Coordenadas obtenidas (JSON): Lon={lon}, Lat={lat}")
                    return {"lon": lon, "lat": lat, "srs": "EPSG:4326"}
        except Exception as e:
            # print(f"  ⚠ Método JSON falló: {e}")
            pass

        # Método 2: Extraer del GML de parcela
        try:
            # print("  Intentando extraer coordenadas del GML de parcela...")
            url_gml = "https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx"
            params = {
                "service": "wfs",
                "version": "2.0.0",
                "request": "GetFeature",
                "STOREDQUERY_ID": "GetParcel", # Corregido: 'STOREDQUERY_ID'
                "refcat": ref,
                "srsname": "EPSG:4326",
            }

            response = safe_get(url_gml, params=params, timeout=30)
            if response.status_code == 200:
                root = ET.fromstring(response.content)

                namespaces = {
                    "gml": "http://www.opengis.net/gml/3.2",
                    "cp": "http://inspire.ec.europa.eu/schemas/cp/4.0",
                    "gmd": "http://www.isotc211.org/2005/gmd",
                }

                # Buscar coordenadas en pos o posList
                for ns_uri in namespaces.values():
                    # Buscar pos (coordenada de centro o un punto)
                    pos_list = root.findall(f".//{{{ns_uri}}}pos")
                    if pos_list:
                        coords_text = pos_list[0].text.strip().split()
                        if len(coords_text) >= 2:
                            # En el GML de INSPIRE, a menudo es Lat, Lon (orden de eje)
                            v1 = float(coords_text[0])
                            v2 = float(coords_text[1])
                            # Heurística para Lat/Lon en España
                            if 36 <= v1 <= 44 and -10 <= v2 <= 5: 
                                lat, lon = v1, v2
                            elif 36 <= v2 <= 44 and -10 <= v1 <= 5:
                                lat, lon = v2, v1
                            else: # Por defecto (Lat, Lon)
                                lat, lon = v1, v2
                                
                            print(f"  Coordenadas extraídas del GML: Lon={lon}, Lat={lat}")
                            return {"lon": lon, "lat": lat, "srs": "EPSG:4326"}

                    # Buscar posList (coordenadas de polígono)
                    pos_list = root.findall(f".//{{{ns_uri}}}posList")
                    if pos_list:
                        coords_text = pos_list[0].text.strip().split()
                        if len(coords_text) >= 2:
                            # Tomamos el primer par como aproximación
                            v1 = float(coords_text[0])
                            v2 = float(coords_text[1])
                            # Heurística
                            if 36 <= v1 <= 44 and -10 <= v2 <= 5: 
                                lat, lon = v1, v2
                            elif 36 <= v2 <= 44 and -10 <= v1 <= 5:
                                lat, lon = v2, v1
                            else:
                                lat, lon = v1, v2
                                
                            print(f"  Coordenadas extraídas del GML (PosList): Lon={lon}, Lat={lat}")
                            return {"lon": lon, "lat": lat, "srs": "EPSG:4326"}
        except Exception as e:
            # print(f"  ⚠ Extracción de GML falló: {e}")
            pass

        # Método 3: Servicio XML original
        try:
            url = (
                "https://ovc.catastro.meh.es/ovcservweb/ovcswlocalizacionrc/"
                "ovccoordenadas.asmx/Consulta_RCCOOR"
            )
            params = {"SRS": "EPSG:4326", "RC": ref}

            response = safe_get(url, params=params, timeout=30)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                coords_element = root.find(
                    ".//{http://www.catastro.meh.es/}coord"
                )
                if coords_element is not None:
                    geo = coords_element.find(
                        "{http://www.catastro.meh.es/}geo"
                    )
                    if geo is not None:
                        xcen = geo.find(
                            "{http://www.catastro.meh.es/}xcen"
                        )
                        ycen = geo.find(
                            "{http://www.catastro.meh.es/}ycen"
                        )

                        if xcen is not None and ycen is not None:
                            lon = float(xcen.text)
                            lat = float(ycen.text)
                            print(f"  Coordenadas obtenidas (XML): Lon={lon}, Lat={lat}")
                            return {"lon": lon, "lat": lat, "srs": "EPSG:4326"}
        except Exception as e:
            # print(f"  ⚠ Método XML falló: {e}")
            pass

        print("  ✗ No se pudieron obtener coordenadas por ningún método")
        return None

    def convertir_coordenadas_a_etrs89(self, lon, lat):
        """Convierte coordenadas WGS84 a ETRS89/UTM (aproximación)."""
        # Esto es una aproximación para determinar la zona UTM correcta
        if lon < -6:
            zona = 29
            epsg = 25829
        elif lon < 0:
            zona = 30
            epsg = 25830
        else:
            zona = 31
            epsg = 25831

        return {"epsg": epsg, "zona": zona}

    def calcular_bbox(self, lon, lat, buffer_metros=200):
        """Calcula un BBOX (WGS84) alrededor de un punto para WMS."""
        # Esto es una aproximación, no una conversión cartográfica exacta
        buffer_lon = buffer_metros / 85000
        buffer_lat = buffer_metros / 111000

        minx = lon - buffer_lon
        miny = lat - buffer_lat
        maxx = lon + buffer_lon
        maxy = lat + buffer_lat

        return f"{minx},{miny},{maxx},{maxy}"

    def descargar_consulta_descriptiva_pdf(self, referencia):
        """Descarga el PDF oficial de consulta descriptiva"""
        ref = self.limpiar_referencia(referencia)
        del_code, mun_code = self.extraer_del_mun(ref)
        
        # El endpoint requiere los 5 primeros dígitos (código provincial + municipal)
        del_code = ref[:2]
        mun_code = ref[2:5]
        
        url = f"https://www1.sedecatastro.gob.es/CYCBienInmueble/SECImprimirCroquisYDatos.aspx?del={del_code}&mun={mun_code}&refcat={ref}"
        
        # Corrección de la ruta de guardado
        filename = self.output_dir / f"{ref}_consulta_oficial.html"
        
        if os.path.exists(filename):
            print(f"  ↩ Ficha oficial ya existe")
            return True
        
        try:
            response = safe_get(url, timeout=30)
                
            if response.status_code == 200:
                # Verificar si hay contenido (incluso si no es PDF)
                if len(response.content) > 0:
                    with open(filename, "wb") as f:
                        f.write(response.content)
                    
                    # Verificar el tipo de contenido para informar
                    content_type = response.headers.get("Content-Type", "")
                    if content_type.startswith("application/pdf"):
                        print(f"  ✓ Ficha oficial descargada (PDF): {filename}")
                    else:
                        print(f"  ✓ Archivo oficial descargado (tipo: {content_type}): {filename}")
                    return True
                else:
                    print(f"  ✗ Ficha oficial vacía (Status {response.status_code})")
                    return False
            else:
                print(f"  ✗ Ficha oficial falló (Status {response.status_code})")
                return False
                    
        except Exception as e:
            print(f"  ✗ Error descargando Ficha: {e}")
            return False

    # --------- NUEVO: utilidades de geometría / contorno ---------

    def extraer_coordenadas_gml(self, gml_file):
        """Extrae las coordenadas del polígono desde el archivo GML."""
        try:
            tree = ET.parse(gml_file)
            root = tree.getroot()

            coords = []

            # posList GML 3.2 (Lat Lon)
            for pos_list in root.findall(
                ".//{http://www.opengis.net/gml/3.2}posList"
            ):
                parts = pos_list.text.strip().split()

                # Manejar posList con coordenadas 2D o 3D (x y [z])
                if len(parts) % 3 == 0:
                    # asume triples (x,y,z) y descarta z
                    for i in range(0, len(parts), 3):
                        if i + 1 < len(parts):
                            coords.append((float(parts[i]), float(parts[i + 1])))
                else:
                    for i in range(0, len(parts), 2):
                        if i + 1 < len(parts):
                            # Almacenamos el par como está. Asumimos que es Lat/Lon o Lon/Lat.
                            coords.append((float(parts[i]), float(parts[i + 1])))

            # pos individuales si no hay posList
            if not coords:
                for pos in root.findall(
                    ".//{http://www.opengis.net/gml/3.2}pos"
                ):
                    parts = pos.text.strip().split()
                    if len(parts) >= 2:
                        coords.append((float(parts[0]), float(parts[1])))

            if coords:
                print(f"  ✓ Extraídas {len(coords)} coordenadas del GML")
                return coords

            print("  ⚠ No se encontraron coordenadas en el GML")
            return None

        except Exception as e:
            print(f"  ⚠ Error extrayendo coordenadas del GML: {e}")
            return None

    def convertir_coordenadas_a_pixel(self, coords, bbox, width, height):
        """
        Convierte coordenadas (Lat/Lon o Lon/Lat) a píxeles de la imagen según BBOX WGS84.
        
        Incluye heurística para el orden Lat/Lon vs Lon/Lat.
        """
        try:
            # bbox es 'minx,miny,maxx,maxy' (Lon, Lat)
            minx, miny, maxx, maxy = [float(x) for x in bbox.split(",")] 
            pixels = []

            # Rangos aproximados para España peninsular
            LAT_RANGE = (36, 44) 
            LON_RANGE = (-10, 5)

            for v1, v2 in coords:
                
                # Heurística para decidir el orden
                lat, lon = v1, v2 # Asumimos Lat, Lon (orden de eje del GML/EPSG:4326)
                
                # Caso 1: Lat es v1, Lon es v2 (Orden Lat/Lon)
                if LAT_RANGE[0] <= v1 <= LAT_RANGE[1] and LON_RANGE[0] <= v2 <= LON_RANGE[1]: 
                     lat, lon = v1, v2
                
                # Caso 2: Lon es v1, Lat es v2 (Orden Lon/Lat)
                elif LON_RANGE[0] <= v1 <= LON_RANGE[1] and LAT_RANGE[0] <= v2 <= LAT_RANGE[1]: 
                     lon, lat = v1, v2
                
                # Si no está claro, mantenemos la asunción por defecto Lat=v1, Lon=v2
                else: 
                     lat, lon = v1, v2
                
                # Es crucial que aquí tengamos (Lon, Lat) para el cálculo.
                # Si en el Caso 2 se invirtió, `lon` y `lat` ya tienen los valores correctos.
                # Si en el Caso 1, `lon` y `lat` ya tienen los valores correctos (v2 y v1).

                # Normalización en X (Longitud)
                x_norm = (lon - minx) / (maxx - minx) if maxx != minx else 0.5
                # Normalización en Y (Latitud) (Y se invierte en la imagen: MaxY es el píxel 0)
                y_norm = (maxy - lat) / (maxy - miny) if maxy != miny else 0.5 

                x = max(0, min(width - 1, int(x_norm * width)))
                y = max(0, min(height - 1, int(y_norm * height)))
                pixels.append((x, y))

            return pixels

        except Exception as e:
            print(f"  ⚠ Error convirtiendo coordenadas a píxeles: {e}")
            return None

    def dibujar_contorno_en_imagen(
        self, imagen_path, pixels, output_path, color=(255, 0, 0), width=4
    ):
        """Dibuja el contorno de la parcela sobre una imagen existente."""
        if not PILLOW_AVAILABLE:
            print("  ⚠ Pillow no disponible, no se puede dibujar contorno")
            return False

        try:
            img = Image.open(imagen_path).convert("RGBA")
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            if len(pixels) > 2:
                # Cerrar el polígono
                if pixels[0] != pixels[-1]:
                    pixels = pixels + [pixels[0]]
                draw.line(pixels, fill=color + (255,), width=width)

            # Combina la imagen original con la capa de contorno
            result = Image.alpha_composite(img, overlay).convert("RGB")
            result.save(output_path)
            print(f"  ✓ Contorno dibujado en {output_path}")
            return True

        except Exception as e:
            print(f"  ⚠ Error dibujando contorno: {e}")
            return False

    def superponer_contorno_parcela(self, ref, bbox_wgs84):
        """Superpone el contorno de la parcela sobre plano, ortofoto y composición."""
        ref = self.limpiar_referencia(ref)
        
        # Buscar GML en la raíz o en subcarpeta gml/
        posibles_gml = [
            self.output_dir / f"{ref}_parcela.gml",
            self.output_dir / f"{ref}_parcela.gml"  # Fallback redundante por compatibilidad
        ]
        
        gml_file = None
        for gml_candidate in posibles_gml:
            if os.path.exists(gml_candidate):
                gml_file = gml_candidate
                break
        
        if not gml_file:
            print("  ⚠ No existe GML de parcela, no se puede dibujar contorno")
            return False

        coords = self.extraer_coordenadas_gml(gml_file)
        if not coords:
            return False

        exito = False

        imagenes = [
            (
                self.output_dir / f"{ref}_ortofoto_pnoa.jpg",
                self.output_dir / f"{ref}_ortofoto_pnoa_contorno.jpg",
            ),
            (
                self.output_dir / f"{ref}_plano_catastro.png",
                self.output_dir / f"{ref}_plano_catastro_contorno.png",
            ),
            (
                self.output_dir / f"{ref}_plano_con_ortofoto.png",
                self.output_dir / f"{ref}_plano_con_ortofoto_contorno.png",
            ),
        ]

        for in_path, out_path in imagenes:
            if os.path.exists(in_path):
                try:
                    with Image.open(in_path) as img:
                        w, h = img.size
                    pixels = self.convertir_coordenadas_a_pixel(
                        coords, bbox_wgs84, w, h
                    )
                    if pixels and self.dibujar_contorno_en_imagen(
                        in_path, pixels, out_path
                    ):
                        exito = True
                except Exception as e:
                    print(f"  ⚠ Error procesando imagen {in_path}: {e}")

        return exito

    def generar_mapa_lote(self, all_coords, output_path):
        """Genera un mapa único con todas las parcelas del lote."""
        if not all_coords:
            return False
            
        try:
            # Calcular BBOX global
            min_lon, min_lat, max_lon, max_lat = 180, 90, -180, -90
            
            for coords in all_coords:
                for v1, v2 in coords:
                    # Heurística simple para Lat/Lon vs Lon/Lat (España Lat 36-44, Lon -10-5)
                    lat, lon = v1, v2
                    if 35 < v1 < 45: lat, lon = v1, v2
                    else: lon, lat = v1, v2
                    
                    if lat < min_lat: min_lat = lat
                    if lat > max_lat: max_lat = lat
                    if lon < min_lon: min_lon = lon
                    if lon > max_lon: max_lon = lon
            
            # Margen del 10%
            lat_margin = max((max_lat - min_lat) * 0.1, 0.001)
            lon_margin = max((max_lon - min_lon) * 0.1, 0.001)
            
            min_lat -= lat_margin
            max_lat += lat_margin
            min_lon -= lon_margin
            max_lon += lon_margin
            
            bbox_wgs84 = f"{min_lon},{min_lat},{max_lon},{max_lat}"
            # BBOX para WMS 1.3.0 (Lat, Lon)
            bbox_wms13 = f"{min_lat},{min_lon},{max_lat},{max_lon}"
            
            wms_pnoa_url = "https://www.ign.es/wms-inspire/pnoa-ma"
            params_pnoa = {
                "SERVICE": "WMS",
                "VERSION": "1.3.0",
                "REQUEST": "GetMap",
                "LAYERS": "OI.OrthoimageCoverage",
                "STYLES": "",
                "CRS": "EPSG:4326",
                "BBOX": bbox_wms13,
                "WIDTH": "2048",
                "HEIGHT": "2048",
                "FORMAT": "image/jpeg",
            }
            
            response = safe_get(wms_pnoa_url, params=params_pnoa, timeout=60)
            if response.status_code == 200:
                with open(output_path, "wb") as f:
                    f.write(response.content)
                
                if PILLOW_AVAILABLE:
                    img = Image.open(output_path).convert("RGBA")
                    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
                    draw = ImageDraw.Draw(overlay)
                    
                    width, height = img.size
                    
                    for coords in all_coords:
                        pixels = self.convertir_coordenadas_a_pixel(coords, bbox_wgs84, width, height)
                        if pixels and len(pixels) > 2:
                             if pixels[0] != pixels[-1]:
                                pixels.append(pixels[0])
                             draw.line(pixels, fill=(255, 0, 0, 255), width=3)
                             draw.polygon(pixels, fill=(255, 0, 0, 40))

                    result = Image.alpha_composite(img, overlay).convert("RGB")
                    result.save(output_path)
                    print(f"  ✓ Mapa Global generado: {output_path}")
                    return True
            return False
        except Exception as e:
            print(f"  ⚠ Error generando mapa global: {e}")
            return False

    def generar_gml_global(self, datos_lote, output_path):
        """Genera un archivo GML único con todas las parcelas."""
        try:
            gml_content = ['<?xml version="1.0" encoding="UTF-8"?>', '<gml:FeatureCollection xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:cp="http://inspire.ec.europa.eu/schemas/cp/4.0">', f'<gml:description>Lote de {len(datos_lote)} referencias</gml:description>', '<gml:boundedBy><gml:Envelope srsName="EPSG:4326"><gml:lowerCorner>-180 -90</gml:lowerCorner><gml:upperCorner>180 90</gml:upperCorner></gml:Envelope></gml:boundedBy>']
            for item in datos_lote:
                ref, coords = item.get('referencia'), item.get('geometria')
                if not coords: continue
                coord_str = " ".join([f"{c[0]} {c[1]}" for c in coords])
                gml_content.append(f'<gml:featureMember><cp:CadastralParcel gml:id="{ref}"><cp:nationalCadastralReference>{ref}</cp:nationalCadastralReference><cp:geometry><gml:MultiSurface srsName="EPSG:4326"><gml:surfaceMember><gml:Polygon><gml:exterior><gml:LinearRing><gml:posList>{coord_str}</gml:posList></gml:LinearRing></gml:exterior></gml:Polygon></gml:surfaceMember></gml:MultiSurface></cp:geometry></cp:CadastralParcel></gml:featureMember>')
            gml_content.append('</gml:FeatureCollection>')
            with open(output_path, 'w', encoding='utf-8') as f: f.write("".join(gml_content))
            print(f"  ✓ GML Global generado: {output_path}")
            return True
        except Exception as e:
            print(f"  ⚠ Error generando GML Global: {e}")
            return False

    def generar_xml_lote(self, datos_lote, lote_id, output_path):
        """Genera un XML resumen con los datos de todo el lote."""
        try:
            from datetime import datetime
            xml_content = [
                '<?xml version="1.0" encoding="UTF-8"?>',
                f'<lote_catastral id="{lote_id}" fecha_generacion="{datetime.now().isoformat()}">',
                '  <metadatos>',
                f'    <total_referencias>{len(datos_lote)}</total_referencias>',
                f'    <fecha_procesamiento>{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</fecha_procesamiento>',
                '  </metadatos>',
                '  <referencias>'
            ]
            
            for dato in datos_lote:
                ref = dato.get('referencia', '')
                geom = dato.get('geometria', [])
                xml_content.append(f'    <referencia>')
                xml_content.append(f'      <codigo>{ref}</codigo>')
                xml_content.append(f'      <geometria>')
                xml_content.append(f'        <anillos>{len(geom) if geom else 0}</anillos>')
                xml_content.append(f'      </geometria>')
                xml_content.append(f'    </referencia>')
            
            xml_content.append('  </referencias>')
            xml_content.append('</lote_catastral>')
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(xml_content))
            print(f"  ✓ XML Lote generado: {output_path}")
            return True
        except Exception as e:
            print(f"  ⚠ Error generando XML Lote: {e}")
            return False

    def generar_geojson_lote(self, todas_geometrias, output_path):
        """Genera un GeoJSON combinado con todas las geometrías."""
        try:
            features = []
            for geom in todas_geometrias:
                coords_raw = geom.get('coordenadas', [])
                coords_geojson = []
                
                for p in coords_raw:
                    v1, v2 = p
                    # Heurística simple: España Lat 36-44, Lon -10-5
                    if 35 < v1 < 45: # v1 es Lat
                        coords_geojson.append([v2, v1])
                    else: # v1 es Lon
                        coords_geojson.append([v1, v2])
                
                feature = {
                    "type": "Feature",
                    "properties": {
                        "referencia": geom.get('referencia'),
                        "anillo": geom.get('anillo'),
                        "tipo": "parcela_catastral"
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [coords_geojson]
                    }
                }
                features.append(feature)
            
            geojson_obj = {
                "type": "FeatureCollection",
                "features": features
            }
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(geojson_obj, f, ensure_ascii=False, indent=2)
            print(f"  ✓ GeoJSON Lote generado: {output_path}")
            return True
        except Exception as e:
            print(f"  ⚠ Error generando GeoJSON Lote: {e}")
            return False

    def organizar_lote(self, lote_dir, lote_id, referencias):
        """Organiza los archivos del lote en carpetas temáticas y crea el ZIP."""
        import shutil
        lote_path = Path(lote_dir)
        
        # Estructura de carpetas
        dirs = {
            'Documentacion': ['pdf', 'html', 'xml'],
            'Imagenes': ['jpg', 'png'],
            'Geometria': ['gml', 'kml', 'geojson'],
            'Informes': ['csv', 'json']
        }
        
        for d in dirs:
            (lote_path / d).mkdir(exist_ok=True)
            
        # Mover archivos de referencias individuales
        for ref in referencias:
            ref_dir = lote_path / ref
            if ref_dir.exists():
                for f in ref_dir.iterdir():
                    if f.is_file():
                        ext = f.suffix.lower().replace('.', '')
                        dest_folder = None
                        for d, exts in dirs.items():
                            if ext in exts:
                                dest_folder = d
                                break
                        
                        if dest_folder:
                            shutil.copy2(f, lote_path / dest_folder / f.name)
                
                try:
                    shutil.rmtree(ref_dir)
                except Exception as e:
                    print(f"  ⚠ No se pudo eliminar carpeta {ref_dir}: {e}")

        # Mover archivos globales del lote
        for f in lote_path.glob(f"{lote_id}_*"):
            if f.is_file():
                ext = f.suffix.lower().replace('.', '')
                dest_folder = None
                for d, exts in dirs.items():
                    if ext in exts:
                        dest_folder = d
                        break
                
                if dest_folder:
                    shutil.move(str(f), str(lote_path / dest_folder / f.name))
        
        # Crear ZIP
        zip_path = lote_path / f"{lote_id}.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for folder in dirs:
                folder_path = lote_path / folder
                if folder_path.exists():
                    for f in folder_path.rglob('*'):
                        if f.is_file():
                            zipf.write(f, f.relative_to(lote_path))
                            
        print(f"  📦 Lote organizado y comprimido: {zip_path}")
        return str(zip_path)
    
    # --------- resto de métodos: HTML, descargas, etc. ---------

    def descargar_plano_ortofoto(self, referencia):
        """Descarga el plano con ortofoto usando servicios WMS y guarda geolocalización."""
        ref = self.limpiar_referencia(referencia)

        print("  Obteniendo coordenadas...")
        coords = self.obtener_coordenadas(ref)

        if not coords:
            print("  ✗ No se pudieron obtener coordenadas para generar el plano")
            return False

        lon = coords["lon"]
        lat = coords["lat"]

        bbox_wgs84 = self.calcular_bbox(lon, lat, buffer_metros=200)
        coords_list = bbox_wgs84.split(",")
        # BBOX para WMS 1.3.0 (CRS=EPSG:4326) es Lat, Lon (miny, minx, maxy, maxx)
        bbox_wms13 = (
            f"{coords_list[1]},{coords_list[0]},{coords_list[3]},{coords_list[2]}"
        )

        print("  Generando mapa con ortofoto...")

        # Usar HTTPS cuando sea posible
        wms_url = "https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx"

        params = {
            "SERVICE": "WMS",
            "VERSION": "1.1.1",
            "REQUEST": "GetMap",
            "LAYERS": "Catastro",
            "STYLES": "",
            "SRS": "EPSG:4326", # WMS 1.1.1 usa SRS, y el Catastro necesita Lon/Lat para BBOX
            "BBOX": bbox_wgs84,
            "WIDTH": "1600",
            "HEIGHT": "1600",
            "FORMAT": "image/png",
            "TRANSPARENT": "FALSE",
        }

        try:
            # Plano catastral
            response_catastro = safe_get(
                wms_url, params=params, timeout=60, max_retries=3
            )

            if (
                response_catastro.status_code == 200
                and len(response_catastro.content) > 1000
            ):
                filename_catastro = (
                    self.output_dir / f"{ref}_plano_catastro.png"
                )
                with open(filename_catastro, "wb") as f:
                    f.write(response_catastro.content)
                print(f"  ✓ Plano catastral descargado: {filename_catastro}")
            else:
                print("  ⚠ Error descargando plano catastral")

            ortofotos_descargadas = False

            # PNOA
            try:
                wms_pnoa_url = "https://www.ign.es/wms-inspire/pnoa-ma"
                params_pnoa = {
                    "SERVICE": "WMS",
                    "VERSION": "1.3.0",
                    "REQUEST": "GetMap",
                    "LAYERS": "OI.OrthoimageCoverage",
                    "STYLES": "",
                    "CRS": "EPSG:4326", # WMS 1.3.0 usa CRS
                    "BBOX": bbox_wms13, # BBOX para 1.3.0 (Lat, Lon)
                    "WIDTH": "1600",
                    "HEIGHT": "1600",
                    "FORMAT": "image/jpeg",
                }

                response_pnoa = safe_get(
                    wms_pnoa_url, params=params_pnoa, timeout=60, max_retries=3
                )

                if (
                    response_pnoa.status_code == 200
                    and len(response_pnoa.content) > 5000
                ):
                    filename_ortofoto = (
                        self.output_dir / f"{ref}_ortofoto_pnoa.jpg"
                    )
                    with open(filename_ortofoto, "wb") as f:
                        f.write(response_pnoa.content)
                    print(
                        f"  ✓ Ortofoto PNOA descargada: {filename_ortofoto}"
                    )
                    ortofotos_descargadas = True

                    # Composición opcional
                    if PILLOW_AVAILABLE and response_catastro.status_code == 200:
                        try:
                            # Volver a leer el contenido del plano catastral (si se descargó)
                            if os.path.exists(filename_catastro):
                                with open(filename_catastro, "rb") as f:
                                    img_catastro = Image.open(BytesIO(f.read()))
                            else:
                                img_catastro = Image.open(
                                    BytesIO(response_catastro.content)
                                )
                                
                            img_ortofoto = Image.open(
                                BytesIO(response_pnoa.content)
                            )

                            img_ortofoto = img_ortofoto.convert("RGBA")
                            img_catastro = img_catastro.convert("RGBA")

                            # Asegurar mismo tamaño antes de mezclar
                            if img_ortofoto.size != img_catastro.size:
                                img_ortofoto = img_ortofoto.resize(img_catastro.size, Image.LANCZOS)

                            # Simple alpha blend:
                            resultado = Image.blend(img_ortofoto.convert("RGB"), img_catastro.convert("RGB"), alpha=0.6)


                            filename_composicion = (
                                self.output_dir / f"{ref}_plano_con_ortofoto.png"
                            )
                            resultado.save(filename_composicion, "PNG")
                            print(
                                f"  ✓ Composición creada: {filename_composicion}"
                            )
                        except Exception as e:
                            print(
                                f"  ⚠ No se pudo crear composición: {e}"
                            )
                    else:
                        if not PILLOW_AVAILABLE:
                            print(
                                "  ⚠ Composición omitida (Pillow no instalado)"
                            )

            except Exception as e:
                print(f"  ⚠ PNOA no disponible: {e}")

            # Ortofoto Catastro como respaldo
            if not ortofotos_descargadas:
                try:
                    wms_catastro_orto = wms_url
                    params_orto = {
                        "SERVICE": "WMS",
                        "VERSION": "1.1.1",
                        "REQUEST": "GetMap",
                        "LAYERS": "ORTOFOTOS",
                        "STYLES": "",
                        "SRS": "EPSG:4326",
                        "BBOX": bbox_wgs84,
                        "WIDTH": "1600",
                        "HEIGHT": "1600",
                        "FORMAT": "image/jpeg",
                        "TRANSPARENT": "FALSE",
                    }

                    response_orto = safe_get(
                        wms_catastro_orto, params=params_orto, timeout=60, max_retries=3
                    )

                    if (
                        response_orto.status_code == 200
                        and len(response_orto.content) > 5000
                    ):
                        filename_ortofoto = (
                            self.output_dir / f"{ref}_ortofoto_catastro.jpg"
                        )
                        with open(filename_ortofoto, "wb") as f:
                            f.write(response_orto.content)
                        print(
                            f"  ✓ Ortofoto Catastro descargada: {filename_ortofoto}"
                        )
                        ortofotos_descargadas = True
                except Exception as e:
                    print(f"  ⚠ Ortofoto Catastro no disponible: {e}")

            if not ortofotos_descargadas:
                print("  ⚠ No se pudieron descargar ortofotos automáticamente")
                print(
                    f"  📍 Google Maps: https://www.google.com/maps/search/?api=1&query={lat},{lon}"
                )

            # Geolocalización
            geo_info = {
                "referencia": ref,
                "coordenadas": coords,
                "bbox": bbox_wgs84,
                "url_visor_catastro": (
                    "https://www1.sedecatastro.gob.es/Cartografia/"
                    f"mapa.aspx?refcat={ref}"
                ),
                "url_google_maps": f"https://www.google.com/maps/search/?api=1&query={lat},{lon}",
                "url_google_earth": (
                    "https://earth.google.com/web/@"
                    f"{lat},{lon},100a,500d,35y,0h,0t,0r"
                ),
            }

            filename_geo = self.output_dir / f"{ref}_geolocalizacion.json"
            with open(filename_geo, "w", encoding="utf-8") as f:
                json.dump(geo_info, f, indent=2, ensure_ascii=False)
            print(f"  ✓ Información de geolocalización guardada: {filename_geo}")

            # DIBUJAR CONTORNO
            self.superponer_contorno_parcela(ref, bbox_wgs84)

            return True

        except Exception as e:
            print(f"  ✗ Error descargando plano con ortofoto: {e}")
            return False

    def descargar_consulta_pdf(self, referencia):
        """Descarga el PDF oficial de consulta descriptiva (versión antigua)"""
        # Se renombra para evitar conflicto y se llama a la nueva (descargar_consulta_descriptiva_pdf)
        return self.descargar_consulta_descriptiva_pdf(referencia)

    def descargar_parcela_gml(self, referencia):
        """Descarga la geometría de la parcela en formato GML"""
        ref = self.limpiar_referencia(referencia)
        url = "https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx"
        
        # Corregir: es STOREDQUERY_ID (sin la E)
        params = {
            'service': 'wfs',
            'version': '2.0.0',
            'request': 'GetFeature',
            'STOREDQUERY_ID': 'GetParcel',
            'refcat': ref,
            'srsname': 'EPSG:4326' # Pide el GML en EPSG:4326 para que coincida con el WMS/BBOX
        }
        
        try:
            response = safe_get(url, params=params, timeout=30)
            if response.status_code == 200:
                # Guardar directamente en el directorio de salida (sin subcarpeta gml)
                filename = self.output_dir / f"{ref}_parcela.gml"
                
                # Verificar si es un error XML (ExceptionReport)
                if b'ExceptionReport' in response.content or b'Exception' in response.content:
                    print(f"  ⚠ Parcela GML no disponible para {ref} (Exception Report en la respuesta)")
                    return False

                with open(filename, 'wb') as f:
                    f.write(response.content)
                print(f"  ✓ Parcela GML descargada: {filename}")
                return True
            else:
                print(f"  ✗ Error descargando parcela GML para {ref}: Status {response.status_code}")
                return False
        except Exception as e:
            print(f"  ✗ Error descargando parcela GML para {ref}: {e}")
            return False
    
    def descargar_edificio_gml(self, referencia):
        """Descarga la geometría del edificio en formato GML"""
        ref = self.limpiar_referencia(referencia)
        url = "https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx"
        
        # Corregir: es STOREDQUERY_ID (sin la E)
        params = {
            'service': 'wfs',
            'version': '2.0.0',
            'request': 'GetFeature',
            'STOREDQUERY_ID': 'GetBuilding',
            'refcat': ref,
            'srsname': 'EPSG:4326' # Pide el GML en EPSG:4326
        }
        
        try:
            response = safe_get(url, params=params, timeout=30)
            if response.status_code == 200:
                # Verificar que no sea un error XML
                content = response.content
                if b'ExceptionReport' in content or b'Exception' in content:
                    print(f"  ⚠ Edificio GML no disponible para {ref} (puede ser solo parcela)")
                    return False
                    
                # Guardar directamente en el directorio de salida (sin subcarpeta gml)
                filename = self.output_dir / f"{ref}_edificio.gml"
                with open(filename, 'wb') as f:
                    f.write(content)
                print(f"  ✓ Edificio GML descargado: {filename}")
                return True
            else:
                print(f"  ✗ Error descargando edificio GML para {ref}: Status {response.status_code}")
                return False
        except Exception as e:
            print(f"  ✗ Error descargando edificio GML para {ref}: {e}")
            return False

    def obtener_datos_alfanumericos(self, referencia):
        """Obtiene datos alfanuméricos de la referencia catastral"""
        ref = self.limpiar_referencia(referencia)
        
        # 1. Intentar parsear XML existente
        datos = self.parsear_datos_xml(ref)
        if datos:
            return datos
            
        # 2. Si no existe, intentar descargar y luego parsear
        print(f"  🔍 Descargando datos alfanuméricos para: {ref}")
        if self.descargar_datos_xml(ref):
            datos = self.parsear_datos_xml(ref)
            if datos: return datos
        
        # 3. Fallback
        return {
            'domicilio': 'No disponible',
            'municipio': 'No disponible', 
            'provincia': 'No disponible',
            'superficie_construida': 0,
            'anio_construccion': 0,
            'uso_principal': 'Desconocido'
        }

    def parsear_datos_xml(self, referencia):
        """Parsea el archivo XML de datos para extraer información detallada."""
        ref = self.limpiar_referencia(referencia)
        
        # Buscar el archivo en la raíz o en la subcarpeta de la referencia
        filename = self.output_dir / f"{ref}_datos.xml"
        if not filename.exists():
            filename = self.output_dir / ref / f"{ref}_datos.xml"
            
        if not filename.exists():
            return None

        try:
            tree = ET.parse(filename)
            root = tree.getroot()
            
            datos = {}
            
            # Helper para buscar texto ignorando namespaces
            def find_val(tags):
                for elem in root.iter():
                    if elem.tag.split('}')[-1] in tags:
                        return elem.text
                return None

            datos['municipio'] = find_val(['nm']) or 'Desconocido'
            datos['provincia'] = find_val(['np']) or 'Desconocida'
            datos['domicilio'] = find_val(['ldt']) or f"{find_val(['tv']) or ''} {find_val(['nv']) or ''} {find_val(['pnp']) or ''}".strip()
            datos['superficie_construida'] = float(find_val(['sfc']) or 0)
            datos['superficie_parcela'] = float(find_val(['ss', 'ssu']) or 0) # Superficie suelo
            datos['anio_construccion'] = int(find_val(['ant']) or 0)
            datos['uso_principal'] = find_val(['luso']) or 'Residencial'
            
            return datos
        except Exception as e:
            print(f"  ⚠ Error parseando XML: {e}")
            return None

    def descargar_datos_xml(self, referencia):
        """Descarga los datos alfanuméricos en XML."""
        ref = self.limpiar_referencia(referencia)
        filename = self.output_dir / f"{ref}_datos.xml"
        
        url = "http://ovc.catastro.meh.es/ovcservweb/OVCSWLocalizacionRC/OVCCallejero.asmx/Consulta_DNPRC"
        params = {
            "Provincia": "",
            "Municipio": "",
            "RC": ref
        }
        
        try:
            response = safe_get(url, params=params, timeout=30)
            if response.status_code == 200:
                with open(filename, 'wb') as f:
                    f.write(response.content)
                print(f"  ✓ Datos XML descargados: {filename}")
                return True
            return False
        except Exception as e:
            print(f"  ⚠ Error descargando XML: {e}")
            return False

    def generar_kml(self, referencia):
        """Genera un archivo KML a partir de la geometría o coordenadas."""
        ref = self.limpiar_referencia(referencia)
        filename = self.output_dir / f"{ref}.kml"
        
        try:
            # 1. Intentar usar geometría del GML
            gml_path = self.output_dir / f"{ref}_parcela.gml"
            coords = []
            if gml_path.exists():
                coords = self.extraer_coordenadas_gml(gml_path)
            
            # 2. Si no hay GML, usar centroide
            if not coords:
                center = self.obtener_coordenadas(ref)
                if center:
                    coords = [(center['lat'], center['lon'])]
                    is_point = True
                else:
                    return False
            else:
                is_point = False

            # Construir KML
            kml = [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<kml xmlns="http://www.opengis.net/kml/2.2">',
                '<Document>',
                f'<name>Referencia {ref}</name>',
                '<Style id="poly"><LineStyle><color>ff0000ff</color><width>2</width></LineStyle><PolyStyle><color>7f0000ff</color></PolyStyle></Style>',
                '<Placemark>',
                f'<name>{ref}</name>',
                '<styleUrl>#poly</styleUrl>'
            ]

            if is_point:
                lat, lon = coords[0]
                kml.append(f'<Point><coordinates>{lon},{lat},0</coordinates></Point>')
            else:
                kml.append('<Polygon><outerBoundaryIs><LinearRing><coordinates>')
                for p in coords:
                    # Heurística simple para Lat/Lon vs Lon/Lat
                    v1, v2 = p
                    # España: Lat 36-44, Lon -10-5
                    if 35 < v1 < 45: # v1 es Lat
                        kml.append(f"{v2},{v1},0")
                    else: # v1 es Lon
                        kml.append(f"{v1},{v2},0")
                kml.append('</coordinates></LinearRing></outerBoundaryIs></Polygon>')

            kml.append('</Placemark></Document></kml>')
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(''.join(kml))
            
            print(f"  ✓ KML generado: {filename}")
            return True
            
        except Exception as e:
            print(f"  ⚠ Error generando KML: {e}")
            return False

    def descargar_todo(self, referencia):
        """Descarga todos los documentos para una referencia catastral."""
        print(f"\n{'='*60}")
        print(f"Procesando referencia: {referencia}")
        print(f"{'='*60}")

        ref = self.limpiar_referencia(referencia)
        # Se usa una subcarpeta por referencia para organizar las descargas
        ref_dir = self.output_dir / ref
        ref_dir.mkdir(exist_ok=True)

        old_dir = self.output_dir
        self.output_dir = ref_dir # Se cambia el directorio de salida

        # Es crucial descargar el GML de la parcela ANTES de intentar dibujar el contorno
        # ya que la función superponer_contorno_parcela lo requiere.
        parcela_gml_descargado = self.descargar_parcela_gml(ref)

        resultados = {
            'consulta_descriptiva': self.descargar_consulta_pdf(ref),
            'plano_ortofoto': self.descargar_plano_ortofoto(ref), # Esto llama a superponer_contorno_parcela
            'parcela_gml': parcela_gml_descargado, 
            'edificio_gml': self.descargar_edificio_gml(ref),
            'kml': self.generar_kml(ref),
            'datos_xml': self.descargar_datos_xml(ref),
            'contorno_superpuesto': (self.output_dir / f"{ref}_plano_con_ortofoto_contorno.png").exists()
        }

        self.output_dir = old_dir # Se restaura el directorio de salida
        time.sleep(2)
        return resultados

    
    def descargar_todo_completo(self, referencia):
        """
        Versión mejorada de descargar_todo() que retorna (exito, zip_path)
        Compatible con LoteManager
        Incluye todos los archivos generados en diferentes directorios
        """
        try:
            # Usar el método existente
            resultados = self.descargar_todo(referencia)
            
            # Crear ZIP con todos los archivos generados
            ref_dir = self.output_dir / referencia
            zip_path = self.output_dir / f"{referencia}_completo.zip"
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # 1. Archivos del directorio principal de la referencia
                if ref_dir.exists():
                    for file_path in ref_dir.rglob('*'):
                        if file_path.is_file():
                            # Ruta relativa dentro del ZIP
                            zip_path_relative = file_path.relative_to(ref_dir)
                            zipf.write(file_path, zip_path_relative)
                
                # 2. Archivos del directorio urbanismo (con timestamp)
                urbanismo_base = self.output_dir / "urbanismo"
                if urbanismo_base.exists():
                    for urbanismo_dir in urbanismo_base.glob(f"{referencia}_*"):
                        if urbanismo_dir.is_dir():
                            for file_path in urbanismo_dir.rglob('*'):
                                if file_path.is_file():
                                    # Ruta relativa: urbanismo/timestamp/archivo
                                    zip_path_relative = Path("urbanismo") / urbanismo_dir.name / file_path.relative_to(urbanismo_dir)
                                    zipf.write(file_path, zip_path_relative)
                
                # 3. Buscar y añadir archivos CSV técnicos si existen
                csv_files = list(self.output_dir.glob(f"{referencia}_datos_tecnicos.csv"))
                for csv_file in csv_files:
                    zipf.write(csv_file, csv_file.name)
                
                # 4. Crear un manifiesto de contenidos
                manifest = {
                    "referencia": referencia,
                    "fecha_generacion": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "archivos_incluidos": []
                }

                # Guardar el ZIP temporalmente para poder leerlo y crear el manifiesto
                # (el contexto `with` cerrará el ZIP; no llamar a close() explícitamente)

                # Contar archivos en el ZIP
                with zipfile.ZipFile(zip_path, 'r') as zip_check:
                    for file_info in zip_check.filelist:
                        # Convertir date_time tuple a timestamp
                        date_tuple = file_info.date_time
                        timestamp = time.mktime(date_tuple + (0, 0, -1))  # Ajustar para mktime

                        manifest["archivos_incluidos"].append({
                            "ruta": file_info.filename,
                            "tamaño": file_info.file_size,
                            "fecha": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
                        })
                
                # Reabrir el ZIP para añadir el manifiesto
                with zipfile.ZipFile(zip_path, 'a', zipfile.ZIP_DEFLATED) as zipf_add:
                    manifest_json = json.dumps(manifest, indent=2, ensure_ascii=False)
                    zipf_add.writestr("manifesto.json", manifest_json)
                
            print(f"  📦 ZIP completo creado: {zip_path}")
            return True, zip_path
                
        except Exception as e:
            print(f"Error en descargar_todo_completo: {e}")
            return False, None

    def generar_plano_perfecto(self, gml_path, output_path, ref, info_afecciones=None):
        """
        Genera un plano detallado ('Plano Perfecto') combinando GML, ortofoto y afecciones.
        Este método es requerido por main.py para la generación de informes.
        """
        try:
            print(f"  🎨 Generando Plano Perfecto para {ref}...")
            
            # Si no tenemos tools gráficas, fallamos suavemente copiado la composición si existe
            if not GEOTOOLS_AVAILABLE:
                # Intentar copiar la composición existente si existe
                composicion = self.output_dir / ref / f"{ref}_plano_con_ortofoto.png"
                if composicion.exists():
                     import shutil
                     shutil.copy(composicion, output_path)
                     print(f"  ✓ Plano Perfecto (copia simple) generado en: {output_path}")
                     return True
                return False

            # Cargar GML
            gdf = gpd.read_file(gml_path).to_crs(epsg=3857)
            
            # Configurar plot
            fig, ax = plt.subplots(figsize=(12, 12))
            
            # Calcular bounds con margen
            minx, miny, maxx, maxy = gdf.total_bounds
            margin_x = (maxx - minx) * 0.2
            margin_y = (maxy - miny) * 0.2
            
            ax.set_xlim(minx - margin_x, maxx + margin_x)
            ax.set_ylim(miny - margin_y, maxy + margin_y)
            
            # Añadir mapa base (PNOA)
            try:
                cx.add_basemap(ax, crs=gdf.crs.to_string(), source=cx.providers.Ign.PNOA_M, attribution=False)
            except:
                # Fallback a OpenStreetMap si PNOA falla
                cx.add_basemap(ax, crs=gdf.crs.to_string(), source=cx.providers.OpenStreetMap.Mapnik)
            
            # Dibujar Parcela
            gdf.plot(ax=ax, facecolor="none", edgecolor="#FF0000", linewidth=2.5, zorder=10)
            gdf.plot(ax=ax, facecolor="#FF0000", alpha=0.1, zorder=9) # Relleno sutil
            
            # Añadir título y etiquetas
            plt.title(f"Referencia Catastral: {ref}", fontsize=16, pad=20)
            
            if info_afecciones and info_afecciones.get("total_afectado_percent", 0) > 0:
                ax.text(0.02, 0.98, f"⚠️ AFECCIONES DETECTADAS\n{info_afecciones.get('total_afectado_percent')}% Afectado", 
                        transform=ax.transAxes, fontsize=12, color='white', 
                        bbox=dict(facecolor='red', alpha=0.7))
            
            # Quitar ejes
            ax.axis("off")
            
            # Guardar
            plt.savefig(output_path, dpi=150, bbox_inches='tight', pad_inches=0.1)
            plt.close()
            
            print(f"  ✓ Plano Perfecto generado: {output_path}")
            return True

        except Exception as e:
            print(f"  ⚠ Error generando Plano Perfecto: {e}")
            return False

    def procesar_lista(self, lista_referencias):
        """Procesa una lista de referencias catastrales"""
        print(f"\\nIniciando descarga de {len(lista_referencias)} referencias...")
        print(f"Directorio de salida: {self.output_dir}\\n")
        
        resultados_totales = []
        
        for i, ref in enumerate(lista_referencias, 1):
            print(f"\\n[{i}/{len(lista_referencias)}]")
            resultados = self.descargar_todo(ref)
            resultados_totales.append({
                'referencia': ref,
                'resultados': resultados
            })

        print(f"\\n{'='*60}")
        print("RESUMEN DE DESCARGAS")
        print(f"{'='*60}")
        
        for item in resultados_totales:
            ref = item['referencia']
            res = item['resultados']
            exitos = sum(1 for v in res.values() if v)
            print(f"\\n{ref}: {exitos}/{len(res)} categorías completadas")
            for doc, exitoso in res.items():
                estado = "✓" if exitoso else "✗"
                print(f"  {estado} {doc}")


# Ejemplo de uso
if __name__ == "__main__":
    print("="*60)
    print("DESCARGADOR DE DOCUMENTACIÓN CATASTRAL")
    print("="*60)
    print("\nREQUISITOS:")
    print("- requests: pip install requests")
    print("- Pillow (opcional, para composición de imágenes y contornos): pip install Pillow")
    print("\nDOCUMENTOS QUE SE DESCARGARÁN:")
    print("1. Consulta descriptiva (PDF oficial)")
    print("2. Plano catastral (PNG)")
    print("3. Ortofoto PNOA o Catastro (JPG)")
    print("4. Composición plano + ortofoto (PNG, si Pillow está instalado)")
    print("5. Contornos de parcela superpuestos (PNG/JPG)")
    print("6. Parcela catastral (GML)")
    print("7. Geometría del edificio (GML)")
    print("8. Información de geolocalización (JSON)")
    print("="*60)
    
    # Lista de referencias catastrales - agrega aquí tus referencias reales
    referencias = []  # Ejemplo: ["8884601WF4788S0020LL", "9691201WF4799S0127HR"]
    
    if not referencias:
        print("\n📝 No hay referencias configuradas.")
        print("💡 Agrega tus referencias catastrales reales a la lista 'referencias'")
        print("   Ejemplo: referencias = ['1234567VK1234S0001LL']")
        print("="*60)
        exit()
    
    # Crear el descargador
    downloader = CatastroDownloader(output_dir="documentos_catastro")
    
    # Procesar todas las referencias
    downloader.procesar_lista(referencias)
    
    print("\n✓ Proceso completado!")
    print(f"\nArchivos guardados en subcarpetas dentro de: {downloader.output_dir}/")
    print("\nEstructura de archivos por cada referencia (XXXXX es la referencia):")
    print("  - XXXXX/XXXXX_consulta_oficial.pdf (Consulta descriptiva oficial)")
    print("  - XXXXX/XXXXX_plano_catastro_contorno.png (Plano Catastral con contorno)")
    print("  - XXXXX/XXXXX_ortofoto_pnoa_contorno.jpg (Ortofoto con contorno)")
    print("  - XXXXX/XXXXX_plano_con_ortofoto_contorno.png (Composición con contorno)")
    print("  - XXXXX/XXXXX_parcela.gml (geometría parcela)")
    print("  - XXXXX/XXXXX_edificio.gml (geometría edificio)")
    print("  - XXXXX/XXXXX_geolocalizacion.json (coordenadas y metadatos)")
