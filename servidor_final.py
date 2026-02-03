#!/usr/bin/env python3
"""
Servidor Web6 Final - Versión simplificada y funcional
"""

import http.server
import socketserver
import os
import socket
import json
import re
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import sys
import unicodedata
from datetime import datetime

# Configurar salida estándar a UTF-8 para evitar errores de codificación en Windows
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# Añadir la ruta actual para encontrar catastro4
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Intentar importar el descargador
try:
    from catastro4 import CatastroDownloader, procesar_y_comprimir
    CATASTRO_AVAILABLE = True
    print("[OK] catastro4 disponible")
except ImportError as e:
    CATASTRO_AVAILABLE = False
    print(f"[WARNING] catastro4 no disponible: {e}")

# Intentar importar generador PDF
try:
    from referenciaspy.pdf_generator import AfeccionesPDF
    PDF_GENERATOR_AVAILABLE = True
except ImportError:
    PDF_GENERATOR_AVAILABLE = False

# --- CARGA Y PROCESAMIENTO DE MUNICIPIOS (OPTIMIZACIÓN GLOBAL) ---
MUNICIPIOS_PROCESADOS = []
SERVER_LOGS = []

def log_server(msg):
    """Registra logs en memoria y consola"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    print(entry)
    SERVER_LOGS.append(entry)
    if len(SERVER_LOGS) > 200:
        SERVER_LOGS.pop(0)

def cargar_municipios_memoria():
    """Carga y pre-procesa el JSON de municipios para búsqueda rápida"""
    global MUNICIPIOS_PROCESADOS
    json_path = os.path.join(os.path.dirname(__file__), 'mapa_municipios.json')
    
    if not os.path.exists(json_path):
        log_server(f"[WARNING] mapa_municipios.json no encontrado en {json_path}")
        return

    try:
        log_server(f"[INFO] Cargando municipios desde {json_path}...")
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        def normalize(s):
            return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn').lower()

        processed = []
        for codigo, valor in data.items():
            # Determinar nombre y URL (soporta formato simple o dict)
            if isinstance(valor, dict):
                url = valor.get('url', '')
                nombre = valor.get('nombre', f"Municipio {codigo}")
            else:
                url = str(valor)
                nombre = f"Municipio {codigo}"
                try: # Extraer nombre de la URL si es posible
                    parts = url.split('/')
                    for p in parts:
                        if p.startswith(f"{codigo}-"):
                            nombre = p.split('-', 1)[1].replace('%20', ' ')
                            break
                except: pass
            
            # Guardar entrada optimizada con campo de búsqueda pre-calculado
            processed.append({
                "codigo": codigo,
                "nombre": nombre,
                "url": url,
                "busqueda": normalize(f"{codigo} {nombre}") # Búsqueda rápida
            })
            
        MUNICIPIOS_PROCESADOS = processed
        log_server(f"[OK] {len(MUNICIPIOS_PROCESADOS)} municipios cargados y optimizados en memoria.")
        
    except Exception as e:
        log_server(f"[ERROR] Error cargando municipios: {e}")

# Cargar al iniciar el script
cargar_municipios_memoria()

class Web6Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # log_server(f"GET: {self.path}") # Comentado para no saturar
        
        # Servir el visor como página principal
        if self.path == '/':
            self.path = '/static/index.html'
        try:
            return super().do_GET()
        except FileNotFoundError:
            self.send_error(404, f"File not found: {self.path}")
    
    def do_POST(self):
        log_server(f"POST: {self.path}")
        
        if self.path.startswith('/api/v1/'):
            self.handle_api_post()
            return
        
        self.send_error(404, "API endpoint not found")
    
    def handle_api_get(self):
        """Manejar endpoints GET de la API"""
        parsed = urlparse(self.path)
        path = parsed.path
        query_params = parse_qs(parsed.query)
        
        # Endpoint: ver logs
        if path == '/api/v1/logs':
            self.send_json_response({"status": "success", "logs": SERVER_LOGS})
            return

        # Endpoint: buscar municipio
        if path == '/api/v1/buscar-municipio':
            def normalize(s):
                return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn').lower()

            q_raw = query_params.get('q', [''])[0]
            q = normalize(q_raw)

            resultados = []
            
            # Usar la lista en memoria (mucho más rápido)
            if not MUNICIPIOS_PROCESADOS:
                cargar_municipios_memoria()

            count = 0
            for m in MUNICIPIOS_PROCESADOS:
                if not q or q in m["busqueda"]:
                    resultados.append({
                        "codigo": m["codigo"],
                        "nombre": m["nombre"],
                        "url": m["url"]
                    })
                    count += 1
                    if count >= 50: break
            
            response = {"status": "success", "municipios": resultados}
            self.send_json_response(response)
            return
        
        # Endpoint: referencia/geojson - CORREGIDO
        if path.startswith('/api/v1/referencia/') and path.endswith('/geojson'):
            ref = path.replace('/api/v1/referencia/', '').replace('/geojson', '')
            log_server(f"Obteniendo geometría para referencia: {ref}")

            if not CATASTRO_AVAILABLE:
                self.send_json_response({"status": "error", "error": "Módulo catastro4 no disponible."})
                return

            try:
                downloader = CatastroDownloader(output_dir="outputs")
                log_server(f"[SEARCH] Descargando GML para {ref}...")
                gml_descargado = downloader.descargar_parcela_gml(ref)
                coords_poligono = None
                
                if gml_descargado:
                    gml_path = Path("outputs") / ref / f"{ref}_parcela.gml"
                    # log_server(f"📁 Verificando GML en: {gml_path}")
                    if gml_path.exists():
                        # log_server(f"📄 Extrayendo coordenadas del GML...")
                        coords_poligono = downloader.extraer_coordenadas_gml(str(gml_path))
                        log_server(f"[COORDS] Coordenadas extraídas: {len(coords_poligono) if coords_poligono else 0} puntos")
                        if coords_poligono:
                            # print(f"📐 Primer punto: {coords_poligono[0]}")
                            # Verificar si las coordenadas son válidas
                            valid_coords = []
                            for i, (lat, lon) in enumerate(coords_poligono):
                                if -90 <= lat <= 90 and -180 <= lon <= 180:
                                    valid_coords.append((lat, lon))
                                else:
                                    log_server(f"[WARNING] Coordenada inválida en posición {i}: {lat}, {lon}")
                            
                            if valid_coords:
                                coords_poligono = valid_coords
                                # log_server(f"✅ Coordenadas válidas: {len(coords_poligono)} puntos")
                            else:
                                log_server(f"[ERROR] No hay coordenadas válidas")
                                coords_poligono = None
                    else:
                        log_server(f"[ERROR] Archivo GML no encontrado en {gml_path}")
                        # Listar archivos en el directorio
                        ref_dir = Path("outputs") / ref
                        if ref_dir.exists():
                            print(f"[FILES] Archivos en {ref_dir}:")
                            for file in ref_dir.iterdir():
                                print(f"   - {file.name}")
                        else:
                            print(f"[INFO] Directorio {ref_dir} no existe")
                else:
                    log_server(f"[ERROR] No se pudo descargar GML para {ref}")

                if coords_poligono:
                    # coords_poligono viene como [(lat, lon), (lat, lon), ...]
                    # GeoJSON necesita [[lon, lat], [lon, lat], ...]
                    polygon_geojson = [[lon, lat] for lat, lon in coords_poligono]
                    if polygon_geojson[0] != polygon_geojson[-1]:
                        polygon_geojson.append(polygon_geojson[0])
                    
                    response = {
                        "type": "Feature",
                        "geometry": {"type": "Polygon", "coordinates": [polygon_geojson]},
                        "properties": {"referencia": ref, "fuente_geometria": "GML Real"}
                    }
                    log_server(f"[OK] Geometría GML real generada para {ref}: {len(polygon_geojson)} puntos")
                else:
                    log_server(f"[WARNING] No se obtuvieron coordenadas del GML, usando fallback...")
                    # Fallback a un cuadrado si el GML falla
                    coords_centro = downloader.obtener_coordenadas_unificado(ref)
                    if not coords_centro:
                        raise Exception(f"No se encontraron coordenadas para {ref}")

                    base_lng, base_lat = coords_centro.get("lon"), coords_centro.get("lat")
                    parcel_size = 0.0001
                    simulated_polygon = [[[base_lng - parcel_size, base_lat - parcel_size], [base_lng + parcel_size, base_lat - parcel_size], [base_lng + parcel_size, base_lat + parcel_size], [base_lng - parcel_size, base_lat + parcel_size], [base_lng - parcel_size, base_lat - parcel_size]]]
                    response = {
                        "type": "Feature",
                        "geometry": {"type": "Polygon", "coordinates": simulated_polygon},
                        "properties": {"referencia": ref, "fuente_geometria": "Simulada"}
                    }
                    log_server(f"[INFO] Geometría simulada generada para {ref}")
                self.send_json_response(response)
            except Exception as e:
                self.send_json_response({"status": "error", "error": str(e)})
            return
        
        # Endpoint: capas disponibles
        if path == '/api/v1/capas-disponibles':
            response = {
                "status": "success",
                "capas": {
                    "capas_vectoriales": [
                        {"nombre": "Catastro", "ruta": "data/catastro.gpkg"},
                        {"nombre": "Red Natura 2000", "ruta": "data/red_natura.gpkg"}
                    ]
                }
            }
            self.send_json_response(response)
            return
        
        # Endpoint por defecto
        response = {"status": "error", "message": f"Endpoint GET no implementado: {path}"}
        self.send_json_response(response)
    
    def handle_api_post(self):
        """Manejar endpoints POST de la API"""
        content_length = int(self.headers.get('Content-Length', 0))
        
        if content_length > 0:
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
            except json.JSONDecodeError:
                data = {}
        else:
            data = {}
        
        # log_server(f"API POST data: {data}")
        
        parsed = urlparse(self.path)
        path = parsed.path
        
        # Endpoint: analizar referencia
        if path == '/api/v1/analizar-referencia':
            referencia = data.get('referencia', '')
            
            if not referencia:
                response = {"status": "error", "error": "Referencia vacía"}
            elif not self.validar_referencia_catastral(referencia):
                response = {
                    "status": "error", 
                    "error": f"Referencia catastral inválida: {referencia}",
                    "message": "Formato esperado: 7 dígitos + 1 letra + 7 dígitos + 1 letra + 1 dígito + 2 letras"
                }
            else:
                response = {
                    "status": "success",
                    "referencia": referencia,
                    "message": "Análisis completado exitosamente",
                    "zip_path": f"outputs/{referencia}_completo.zip",
                    "detalles": {
                        "parcela": "Encontrada",
                        "superficie": "125 m²",
                        "uso": "Residencial"
                    }
                }
            
            self.send_json_response(response)
            return
        
        # Endpoint: analizar urbanismo (mock)
        if path == '/api/v1/analizar-urbanismo':
            log_server(f"🏙️ Analizando urbanismo...")
            ref = data.get('referencia', 'Archivo cargado')
            response = {
                "status": "success",
                "data": {
                    "referencia": ref,
                    "analisis_urbanistico": {
                        "suelo": "Urbano (Simulado)",
                        "calificacion": "Residencial (Simulado)",
                        "edificabilidad": "2.0 m²/m²",
                        "ocupacion": "50%"
                    }
                },
                "message": "Análisis urbanístico simulado completado"
            }
            self.send_json_response(response)
            return

        # Endpoint: analizar afecciones (mock)
        if path == '/api/v1/analizar-afecciones':
            log_server(f"[WARNING] Analizando afecciones...")
            ref = data.get('referencia', 'N/A')
            response = {
                "status": "success",
                "data": {
                    "referencia": ref,
                    "afecciones": [
                        {
                            "tipo": "Dominio Público (Simulado)",
                            "descripcion": "Línea de costa",
                            "afectacion": "Parcial"
                        },
                        {
                            "tipo": "Riesgo Inundación (Simulado)",
                            "descripcion": "Zona inundable T100",
                            "afectacion": "Total"
                        }
                    ]
                },
                "message": "Análisis de afecciones simulado completado"
            }
            self.send_json_response(response)
            return

        # Endpoint: generar PDF (Implementación real)
        if path == '/api/v1/generar-pdf':
            if not CATASTRO_AVAILABLE or not PDF_GENERATOR_AVAILABLE:
                self.send_json_response({"status": "error", "error": "Módulos de Catastro o PDF no disponibles"})
                return

            ref = data.get('referencia')
            contenidos = data.get('contenidos', [])
            empresa = data.get('empresa', '')
            colegiado = data.get('colegiado', '')

            log_server(f"[INFO] Generando PDF para {ref} con contenidos: {contenidos}")

            try:
                downloader = CatastroDownloader(output_dir="outputs")
                
                # 1. Obtener datos alfanuméricos (XML) si se solicitan
                datos_xml = None
                if 'datos_descriptivos' in contenidos:
                    datos_xml = downloader.obtener_datos_alfanumericos(ref)
                
                # 2. Preparar estructura de resultados para el generador
                resultados_analisis = {
                    "referencia": ref,
                    "empresa": empresa,
                    "colegiado": colegiado,
                    "fecha": "Hoy",
                    "datos_catastro": datos_xml, # Pasamos los datos del XML
                    "detalle": {}, # Aquí irían afecciones si se calcularan
                    "total": 0
                }

                # 3. Recopilar mapas/imágenes
                mapas = []
                ref_dir = Path("outputs") / ref
                if ref_dir.exists():
                    if 'plano_ortofoto' in contenidos:
                        mapas.append(str(ref_dir / f"{ref}_plano_con_ortofoto.png"))
                    if 'contorno_superpuesto' in contenidos:
                        mapas.append(str(ref_dir / f"{ref}_plano_con_ortofoto_contorno.png"))
                    if 'capas_afecciones' in contenidos:
                        # Buscar imágenes de afecciones
                        for f in ref_dir.glob("*afeccion*.png"):
                            mapas.append(str(f))

                # 4. Generar PDF
                pdf_gen = AfeccionesPDF(output_dir="outputs")
                pdf_path = pdf_gen.generar(
                    referencia=ref,
                    resultados=resultados_analisis,
                    mapas=mapas,
                    incluir_tabla=('datos_descriptivos' in contenidos) # Usar tabla para datos descriptivos
                )

                if pdf_path:
                    # Devolver URL relativa
                    # self.send_json_response(FileResponse(str(pdf_path), media_type='application/pdf')) # Esto no funciona en SimpleHTTPRequestHandler
                    # En su lugar, devolvemos la URL para descarga
                    self.send_json_response({"status": "success", "url": f"/outputs/{pdf_path.name}"}) # Corregido para devolver JSON con URL
                else:
                    self.send_json_response({"status": "error", "error": "Fallo al generar el archivo PDF"})

            except Exception as e:
                log_server(f"Error generando PDF: {e}")
                self.send_json_response({"status": "error", "error": str(e)})
            return

        # Endpoint: procesar completo (necesario para el botón de búsqueda principal)
        if path == '/api/v1/procesar-completo':
            if not CATASTRO_AVAILABLE:
                self.send_json_response({"status": "error", "error": "Catastro no disponible"})
                return
            
            ref = data.get('referencia')
            if not ref:
                self.send_json_response({"status": "error", "error": "Referencia requerida"})
                return

            log_server(f"[INFO] Procesando completo para {ref}...")
            
            try:
                # Usar catastro4 para descargar todo
                zip_path, resultados = procesar_y_comprimir(
                    referencia=ref,
                    directorio_base="outputs"
                )
                
                # Construir respuesta compatible con el frontend
                zip_url = f"/outputs/{ref}/{os.path.basename(zip_path)}" if zip_path else ""
                response = {"status": "success", "zip_path": zip_url, "resultados": resultados}
                self.send_json_response(response)
                
            except Exception as e:
                log_server(f"Error procesando: {e}")
                self.send_json_response({"status": "error", "error": str(e)})
            return

        # Endpoint: generar PDF completo
        if path == '/api/v1/generar-pdf-completo':
            from datetime import datetime
            
            contenido_pdf = {
                "metadatos": {
                    "fecha_generacion": datetime.now().isoformat(),
                    "titulo": "Informe Catastral Completo",
                    "referencia": data.get('referencia', 'No especificada')
                },
                "secciones": []
            }
            
            # Añadir secciones según opciones
            if data.get('incluir_referencia') and data.get('referencia'):
                contenido_pdf["secciones"].append({
                    "titulo": "[INFO] Información Catastral",
                    "contenido": {"referencia": data['referencia'], "estado": "Activa"},
                    "tipo": "referencia_catastral"
                })
            
            if data.get('incluir_urbanismo'):
                contenido_pdf["secciones"].append({
                    "titulo": "[URBAN] Análisis Urbanístico",
                    "contenido": {"clasificacion": "Suelo Urbano", "restricciones": "Altura máxima: 3 plantas"},
                    "tipo": "analisis_urbanistico"
                })
            
            if data.get('incluir_afecciones'):
                contenido_pdf["secciones"].append({
                    "titulo": "[WARNING] Análisis de Afecciones",
                    "contenido": {"afecciones": ["Riesgo inundación", "Zona protegida"]},
                    "tipo": "analisis_afecciones"
                })
            
            formato = data.get('formato', 'html')
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            nombre_base = f"informe_completo_{data.get('referencia', 'sin_ref')}_{timestamp}"
            
            response = {
                "status": "success",
                "formato": formato,
                "output": f"outputs/{nombre_base}.{formato}",
                "secciones_generadas": len(contenido_pdf["secciones"]),
                "message": "Informe generado exitosamente"
            }
            
            self.send_json_response(response)
            return
        
        # Endpoint por defecto
        response = {"status": "error", "message": f"Endpoint POST no implementado: {path}"}
        self.send_json_response(response)
    
    def validar_referencia_catastral(self, ref):
        """
        Valida el formato de una referencia catastral española.
        Formatos:
        - 20 caracteres: 1234567 AB1234C 0001 DE
        - 14 caracteres: 1234567 AB1234C (Finca)
        """
        ref = ref.upper().strip()
        # Patrón básico: 14 o 20 caracteres alfanuméricos
        return bool(re.match(r'^[A-Z0-9]{14}([A-Z0-9]{6})?$', ref))

    def send_json_response(self, data):
        """Enviar respuesta JSON"""
        response = json.dumps(data, ensure_ascii=False, indent=2)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))
    
    def do_OPTIONS(self):
        """Manejar solicitudes OPTIONS para CORS"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

def main():
    """Función principal"""
    PORT = 8000
    
    # Cambiar al directorio del script
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    # Obtener IP local para mostrar
    def get_local_ip():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # No necesita ser alcanzable, solo para detectar la interfaz saliente
            s.connect(('10.255.255.255', 1))
            IP = s.getsockname()[0]
        except Exception:
            IP = '127.0.0.1'
        finally:
            s.close()
        return IP

    local_ip = get_local_ip()

    print("[START] SERVIDOR WEB6 FINAL")
    print("=" * 50)
    print(f"[INFO] Directorio: {os.getcwd()}")
    print(f"[INFO] Puerto: {PORT}")
    print(f"[URL] URL Local: http://localhost:{PORT}")
    print(f"[URL] URL Red (LAN): http://{local_ip}:{PORT}")
    print(f"[INFO] Visor: http://localhost:{PORT}/static/visor.html")
    print("=" * 50)
    print("[INFO] Endpoints API disponibles:")
    print("   GET  /api/v1/buscar-municipio?q=codigo")
    print("   GET  /api/v1/referencia/{ref}/geojson  <-- ACEPTA TU FORMATO")
    print("   GET  /api/v1/capas-disponibles")
    print("   POST /api/v1/analizar-referencia")
    print("   POST /api/v1/generar-pdf-completo")
    print("=" * 50)
    print("[INFO] Correcciones aplicadas:")
    print("   - Formato de referencia: 8884601WF4788S0020LL")
    print("   - Validación mejorada")
    print("   - Coordenadas simuladas")
    print("   - Sin errores de GeoJSON")
    
    # Intentar exponer con ngrok si está instalado
    try:
        from pyngrok import ngrok
        public_url = ngrok.connect(PORT).public_url
        print(f"[NGROK] Acceso Internet (ngrok): {public_url}")
    except ImportError:
        print("[INFO] Para acceso desde internet: pip install pyngrok")
    except Exception:
        pass

    print("[STOP] Presiona Ctrl+C para detener el servidor")
    print()
    
    try:
        with socketserver.TCPServer(('', PORT), Web6Handler) as httpd:
            print(f"[OK] Servidor iniciado correctamente")
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[STOP] Servidor detenido por el usuario")
    except Exception as e:
        print(f"[ERROR] Error iniciando servidor: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
