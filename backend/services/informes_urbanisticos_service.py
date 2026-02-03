#!/usr/bin/env python3
"""
Servicio de Informes Urbanísticos
"""

import json
import os
import sys
import csv
from typing import Dict, Any, Optional, List
from shapely.geometry import Polygon
from pathlib import Path

# Asegurar que el directorio raíz está en el path para importar catastro4
root_dir = str(Path(__file__).parents[2])
if root_dir not in sys.path:
    sys.path.append(root_dir)

# Intentar importar el generador de PDF
try:
    from referenciaspy.pdf_generator import AfeccionesPDF
    PDF_GENERATOR_AVAILABLE = True
except ImportError:
    PDF_GENERATOR_AVAILABLE = False

class InformeUrbanistico:
    """Clase principal para generar informes urbanísticos"""
    
    def __init__(self, config_file: str = "urbanismo_config.json"):
        """
        Inicializa el generador de informes
        """
        self.config_file = config_file
        self.config = self._cargar_configuracion()
        # Directorio de salida por defecto (ajustar según configuración real si es necesario)
        self.output_dir = os.path.join(root_dir, "outputs")
    
    def _cargar_configuracion(self) -> Dict[str, Any]:
        """
        Carga la configuración desde el archivo JSON
        """
        config_default = {
            "coeficientes_edificabilidad": {
                "residencial": 0.6,
                "comercial": 0.8,
                "industrial": 1.0,
                "terciario": 0.7
            },
            "usos_principales": {
                "residencial": "Vivienda",
                "comercial": "Comercio", 
                "industrial": "Industria",
                "terciario": "Servicios"
            },
            "afecciones_territoriales": [
                "Patrimonio Cultural",
                "Riesgo de Inundación",
                "Protección Ambiental",
                "Suelo Rústico",
                "Zona Arqueológica",
                "Via Pecuaria",
                "Dominio Público Hidráulico",
                "Costas Marítimas"
            ]
        }
        
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                return {**config_default, **config}
            else:
                # Crear archivo de configuración por defecto
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(config_default, f, indent=2, ensure_ascii=False)
                return config_default
        except Exception as e:
            print(f"Error cargando configuración: {e}")
            return config_default
    
    def generar_informe_completo(self, ref_catastral: str = None, provincia: str = None, 
                                municipio: str = None, via: str = None, numero: str = None,
                                geometria_anillos: List = None, datos_sede: Dict = None, 
                                datos_registro: Dict = None) -> Dict[str, Any]:
        """
        Genera un informe urbanístico completo con soporte para geometría y datos adicionales
        """
        try:
            # Obtener datos de la parcela
            datos_parcela = self._obtener_datos_parcela(ref_catastral, provincia, municipio, via, numero)
            
            # Integrar geometría de anillos si se proporciona
            if geometria_anillos:
                datos_parcela.update(self._procesar_geometria_anillos(geometria_anillos))
            
            # Integrar datos de sede si se proporcionan
            if datos_sede:
                datos_parcela.update(self._procesar_datos_sede(datos_sede))
            
            # Realizar análisis técnico
            analisis_tecnico = self._realizar_analisis_tecnico(datos_parcela)
            
            # Obtener clasificación del suelo
            clasificacion_suelo = self._obtener_clasificacion_suelo(datos_parcela)
            
            # Analizar afecciones territoriales
            afecciones = self._analizar_afecciones_territoriales(datos_parcela)
            
            # Cruzar con Registro de la Propiedad si hay datos
            cruce_registro = None
            if datos_registro:
                cruce_registro = self._cruzar_registro_propiedad(datos_registro, datos_parcela)
            
            # Generar PDF si el módulo está disponible
            url_pdf = None
            if PDF_GENERATOR_AVAILABLE:
                url_pdf = self._generar_pdf_informe(ref_catastral, datos_parcela, clasificacion_suelo, analisis_tecnico, afecciones)

            # Generar CSV
            url_csv = self._generar_csv_informe(ref_catastral, datos_parcela, clasificacion_suelo, analisis_tecnico, afecciones)

            # Construir respuesta final
            resultado = {
                "referencia_catastral": ref_catastral,
                "direccion": datos_parcela.get("direccion_completa", f"{via} {numero}, {municipio}, {provincia}" if via and numero else "Sin especificar"),
                "datos_parcela": datos_parcela,
                "clasificacion_suelo": clasificacion_suelo,
                "analisis_tecnico": analisis_tecnico,
                "afecciones_territoriales": afecciones,
                "cruce_registro_propiedad": cruce_registro,
                "url_csv": url_csv,
                "url_pdf": url_pdf,
                "fecha_informe": self._get_fecha_actual(),
                "configuracion_aplicada": {
                    "coeficientes_usados": self.config['coeficientes_edificabilidad'],
                    "afecciones_evaluadas": self.config['afecciones_territoriales'],
                    "geometria_procesada": geometria_anillos is not None,
                    "datos_sede_usados": datos_sede is not None,
                    "datos_registro_usados": datos_registro is not None
                }
            }
            return resultado
            
        except Exception as e:
            return {
                "error": f"Error generando informe: {str(e)}",
                "referencia_catastral": ref_catastral
            }
    
    def _generar_pdf_informe(self, ref, datos_parcela, clasificacion, analisis, afecciones):
        """
        Adapta los datos y llama a AfeccionesPDF para generar el documento
        """
        try:
            # 1. Buscar mapas existentes en la carpeta de salida
            mapas = []
            ref_dir = Path(self.output_dir) / ref
            if ref_dir.exists():
                # Priorizar composición y planos
                for nombre in [f"{ref}_plano_con_ortofoto_contorno.png", f"{ref}_plano_con_ortofoto.png", f"{ref}_plano_catastro.png", f"{ref}_ortofoto_pnoa.jpg"]:
                    p = ref_dir / nombre
                    if p.exists():
                        mapas.append(str(p))
            
            # 2. Adaptar estructura de datos para AfeccionesPDF
            # AfeccionesPDF espera: detalle, parametros_urbanisticos, afecciones_detectadas
            
            # Adaptar afecciones para la tabla 'detalle'
            detalle_afecciones = {}
            lista_afecciones_detectadas = []
            
            for k, v in afecciones.items():
                afectada = v.get('afectada', False) if isinstance(v, dict) else v
                if afectada:
                    detalle_afecciones[k] = 100.0 # Asumimos 100% si es booleano True
                    lista_afecciones_detectadas.append({
                        "tipo": "Afección Territorial",
                        "capa": k,
                        "elementos": "1",
                        "descripcion": v.get('descripcion', '') if isinstance(v, dict) else "Detectada"
                    })

            # Adaptar parámetros urbanísticos
            params_urb = {
                "clasificacion": {"valor": clasificacion.get("clasificacion"), "nota": "Clase de suelo"},
                "calificacion": {"valor": clasificacion.get("calificacion"), "nota": "Zona"},
                "uso_principal": {"valor": clasificacion.get("uso_principal"), "nota": "Uso característico"},
                "superficie_parcela": {"valor": analisis.get("superficie_terreno_m2"), "nota": "Catastro"},
                "edificabilidad_maxima": {"valor": analisis.get("edificabilidad_maxima_m2"), "nota": "m² techo (Estimado)"},
                "ocupacion_maxima": {"valor": f"{analisis.get('porcentaje_ocupacion')}%", "nota": "Estimada"},
            }

            # Estructura completa para el generador
            datos_para_pdf = {
                "area_parcela_m2": analisis.get("superficie_terreno_m2", 0),
                "area_afectada_m2": 0, # Pendiente de cálculo geométrico real
                "detalle": detalle_afecciones,
                "total": 100.0 if detalle_afecciones else 0.0,
                "analisis_avanzado": True,
                "parametros_urbanisticos": params_urb,
                "afecciones_detectadas": lista_afecciones_detectadas
            }

            # 3. Instanciar y generar
            pdf_gen = AfeccionesPDF(output_dir=self.output_dir)
            pdf_path = pdf_gen.generar(
                referencia=ref,
                resultados=datos_para_pdf,
                mapas=mapas,
                incluir_tabla=True
            )
            
            if pdf_path:
                # Devolver URL relativa
                return f"/outputs/{pdf_path.name}"
            return None

        except Exception as e:
            print(f"Error generando PDF integrado: {e}")
            return None

    def _generar_csv_informe(self, ref, datos_parcela, clasificacion, analisis, afecciones):
        """Genera un archivo CSV con los datos del informe"""
        try:
            filename = f"{ref}_informe_urbanistico.csv"
            # Asegurar que el directorio existe
            ref_dir = Path(self.output_dir) / ref
            ref_dir.mkdir(parents=True, exist_ok=True)
            filepath = ref_dir / filename
            
            # Aplanar datos para CSV
            row = {
                "Referencia Catastral": ref,
                "Direccion": datos_parcela.get("direccion_completa", ""),
                "Uso Principal": datos_parcela.get("uso_principal", ""),
                "Superficie Suelo (m2)": analisis.get("superficie_terreno_m2", 0),
                "Superficie Construida (m2)": analisis.get("superficie_construida_m2", 0),
                "Edificabilidad Max (m2)": analisis.get("edificabilidad_maxima_m2", 0),
                "Clasificacion Suelo": clasificacion.get("clasificacion", ""),
                "Calificacion": clasificacion.get("calificacion", "")
            }
            
            # Añadir afecciones como columnas
            for k, v in afecciones.items():
                afectada = v.get('afectada', False) if isinstance(v, dict) else v
                row[f"Afeccion_{k}"] = "SI" if afectada else "NO"

            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=row.keys(), delimiter=';')
                writer.writeheader()
                writer.writerow(row)
                
            return f"/outputs/{ref}/{filename}"
        except Exception as e:
            print(f"Error generando CSV: {e}")
            return None

    def _obtener_datos_parcela(self, ref_catastral: str = None, provincia: str = None, 
                              municipio: str = None, via: str = None, numero: str = None) -> Dict[str, Any]:
        """
        Obtiene datos de la parcela integrando con CatastroDownloader
        """
        try:
            if ref_catastral:
                try:
                    from catastro4 import CatastroDownloader
                    downloader = CatastroDownloader(output_dir="outputs")
                    
                    # 1. Obtener datos alfanuméricos
                    datos_xml = downloader.obtener_datos_alfanumericos(ref_catastral) or {}
                    
                    # 2. Obtener coordenadas
                    coords = downloader.obtener_coordenadas_unificado(ref_catastral) or {}
                    
                    return {
                        "superficie_terreno": float(datos_xml.get("superficie_parcela", 850)),
                        "superficie_construida": float(datos_xml.get("superficie_construida", 180)),
                        "uso_principal": datos_xml.get("uso_principal", "residencial").lower(),
                        "ano_construccion": int(datos_xml.get("anio_construccion", 2000)) if datos_xml.get("anio_construccion", "").isdigit() else 2000,
                        "estado_conservacion": "Bueno",
                        "numero_plantas": 1,
                        "coordenadas": [coords.get("lon", -4.42), coords.get("lat", 36.72)],
                        "ref_catastral": ref_catastral,
                        "direccion_completa": datos_xml.get("domicilio", f"{via} {numero}, {municipio}, {provincia}" if via and numero else "Sin especificar")
                    }
                except Exception as e_cat:
                    print(f"Error consultando Catastro: {e_cat}")

            # Fallback / Caso sin referencia
            return {
                "superficie_terreno": 1000,
                "superficie_construida": 200,
                "uso_principal": "residencial",
                "ano_construccion": 2000,
                "estado_conservacion": "Bueno",
                "numero_plantas": 2,
                "coordenadas": [-4.4250, 36.7200],
                "ref_catastral": ref_catastral or "Sin especificar",
                "direccion_completa": f"{via} {numero}, {municipio}, {provincia}" if via and numero else "Sin especificar"
            }
        except Exception as e:
            raise Exception(f"Error obteniendo datos de la parcela: {str(e)}")
    
    def _realizar_analisis_tecnico(self, datos_parcela: Dict[str, Any]) -> Dict[str, Any]:
        """
        Realiza el análisis técnico de la parcela con manejo de errores
        """
        try:
            uso = datos_parcela.get('uso_principal', 'residencial')
            coef = self.config['coeficientes_edificabilidad'].get(uso, 0.6)
            
            sup_terreno = datos_parcela.get('superficie_terreno', 0)
            sup_construida = datos_parcela.get('superficie_construida', 0)
            
            if sup_terreno <= 0:
                raise ValueError("La superficie del terreno debe ser mayor que cero")
            
            edificabilidad_maxima = sup_terreno * coef
            edificabilidad_actual = sup_construida
            edificabilidad_disponible = edificabilidad_maxima - edificabilidad_actual
            
            return {
                "superficie_terreno_m2": round(sup_terreno, 2),
                "superficie_construida_m2": round(sup_construida, 2),
                "edificabilidad_maxima_m2": round(edificabilidad_maxima, 2),
                "edificabilidad_actual_m2": round(edificabilidad_actual, 2),
                "edificabilidad_disponible_m2": round(max(0, edificabilidad_disponible), 2),
                "coeficiente_edificabilidad": coef,
                "porcentaje_ocupacion": round((sup_construida / sup_terreno) * 100, 2) if sup_terreno > 0 else 0,
                "densidad_neta": round(sup_construida / sup_terreno, 2) if sup_terreno > 0 else 0
            }
        except Exception as e:
            raise Exception(f"Error en análisis técnico: {str(e)}")
    
    def _obtener_clasificacion_suelo(self, datos_parcela: Dict[str, Any]) -> Dict[str, Any]:
        """
        Obtiene la clasificación del suelo con manejo de errores
        """
        try:
            uso = datos_parcela.get('uso_principal', 'residencial')
            coordenadas = datos_parcela.get('coordenadas', [0, 0])
            
            # Clasificación basada en uso y configuración
            clasificaciones = self.config.get('clasificaciones_suelo', {})
            calificaciones = self.config.get('calificaciones', {})
            
            # Determinar clasificación según coordenadas (simulación)
            if abs(coordenadas[0]) < 0.5 and abs(coordenadas[1]) < 0.5:  # Centro urbano
                clasificacion = clasificaciones.get('urbano', 'Suelo Urbano')
                calificacion = calificaciones.get('residencial_consolidado', 'Residencial Consolidado')
            else:
                clasificacion = clasificaciones.get('urbanizable', 'Suelo Urbanizable')
                calificacion = calificaciones.get('residencial_en_desarrollo', 'Residencial en Desarrollo')
            
            return {
                "clasificacion": clasificacion,
                "calificacion": calificacion,
                "uso_principal": self.config['usos_principales'].get(uso, 'Vivienda'),
                "densidad_edificatoria": "Media",
                "ordenanza": "Plan General Municipal",
                "zona": "Centro Urbano" if clasificacion == "Suelo Urbano" else "Periferia",
                "sector": "Residencial" if uso == "residencial" else "Terciario"
            }
        except Exception as e:
            raise Exception(f"Error obteniendo clasificación del suelo: {str(e)}")
    
    def _analizar_afecciones_territoriales(self, datos_parcela: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analiza las afecciones territoriales con manejo de errores
        """
        try:
            coordenadas = datos_parcela.get('coordenadas', [0, 0])
            afecciones = self.config.get('afecciones_territoriales', [])
            
            if not afecciones:
                raise ValueError("No hay afecciones territoriales configuradas")
            
            # Simulación de afecciones basada en coordenadas
            afecciones_detectadas = {}
            
            for afeccion in afecciones:
                try:
                    afectado = self._evaluar_afeccion(afeccion, coordenadas, datos_parcela)
                    afecciones_detectadas[afeccion] = {
                        "afectada": afectado,
                        "descripcion": self._get_descripcion_afeccion(afeccion),
                        "restriccion": self._get_restriccion_afeccion(afeccion)
                    }
                except Exception as e:
                    print(f"Error evaluando afección {afeccion}: {e}")
                    afecciones_detectadas[afeccion] = {
                        "afectada": False,
                        "descripcion": "Error en evaluación",
                        "restriccion": "No determinada"
                    }
            
            return afecciones_detectadas
        except Exception as e:
            raise Exception(f"Error analizando afecciones territoriales: {str(e)}")
    
    def _get_fecha_actual(self) -> str:
        """
        Obtiene la fecha actual formateada con manejo de errores
        """
        try:
            from datetime import datetime
            return datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        except Exception as e:
            return f"Error obteniendo fecha: {str(e)}"
    
    def _evaluar_afeccion(self, afeccion: str, coordenadas: List[float], datos_parcela: Dict[str, Any]) -> bool:
        """
        Evalúa si una parcela está afectada por una afección específica
        """
        x, y = coordenadas
        if "Riesgo de Inundación" in afeccion:
            return y < 36.71
        elif "Costas Marítimas" in afeccion:
            return y > 36.73
        elif "Patrimonio Cultural" in afeccion:
            return abs(x + 4.42) < 0.02
        else:
            import random
            return random.random() < 0.3
    
    def _get_descripcion_afeccion(self, afeccion: str) -> str:
        """
        Obtiene descripción detallada de una afección
        """
        descripciones = {
            "Patrimonio Cultural": "Protección de bienes de interés cultural",
            "Riesgo de Inundación": "Zona con riesgo de inundación periódica",
            "Protección Ambiental": "Área protegida por normativa ambiental",
            "Suelo Rústico": "Suelo no urbanizable con protección agrícola",
            "Zona Arqueológica": "Zona con yacimientos arqueológicos",
            "Vía Pecuaria": "Trayecto tradicional de ganado",
            "Dominio Público Hidráulico": "Zona de servidumbre de cauces públicos",
            "Costas Marítimas": "Zona de servidumbre de protección marítima"
        }
        return descripciones.get(afeccion, "Afección territorial específica")
    
    def _get_restriccion_afeccion(self, afeccion: str) -> str:
        """
        Obtiene el tipo de restricción de una afección
        """
        restricciones = {
            "Patrimonio Cultural": "Prohibición de demolición",
            "Riesgo de Inundación": "Limitación de uso bajo rasante",
            "Protección Ambiental": "Uso restringido",
            "Suelo Rústico": "No edificable",
            "Zona Arqueológica": "Autorización previa obligatoria",
            "Vía Pecuaria": "Servidumbre de paso",
            "Dominio Público Hidráulico": "Zona no edificable",
            "Costas Marítimas": "Servidumbre de 100m"
        }
        return restricciones.get(afeccion, "Restricción específica")
    
    def _procesar_geometria_anillos(self, geometria_anillos: List) -> Dict[str, Any]:
        """
        Procesa geometría de anillos para obtener datos métricos precisos.
        Detecta automaticamente si las coordenadas están en grados o metros.
        """
        try:
            if not geometria_anillos or not isinstance(geometria_anillos, list):
                return {"error": "Geometría de anillos no válida"}
            
            try:
                import geopandas as gpd
                from shapely.geometry import Polygon as ShapelyPolygon
                GEOPANDAS_AVAILABLE = True
            except ImportError:
                GEOPANDAS_AVAILABLE = False
            
            anillo_ext = geometria_anillos[0]
            huecos = geometria_anillos[1:]
            
            p = anillo_ext[0]
            is_degrees = abs(p[0]) < 180 and abs(p[1]) < 180

            if GEOPANDAS_AVAILABLE:
                poly = ShapelyPolygon(anillo_ext, huecos)
                source_crs = "EPSG:4326" if is_degrees else "EPSG:25830"
                gdf = gpd.GeoDataFrame(geometry=[poly], crs=source_crs)
                
                if is_degrees:
                    gdf = gdf.to_crs(epsg=25830)
                
                area_ocupacion = gdf.geometry.area.iloc[0]
                perimetro = gdf.geometry.length.iloc[0]
                
                area_patios = 0
                if huecos:
                    gdf_patios = gpd.GeoDataFrame(geometry=[ShapelyPolygon(h) for h in huecos], crs=source_crs)
                    if is_degrees:
                        gdf_patios = gdf_patios.to_crs(epsg=25830)
                    area_patios = gdf_patios.geometry.area.sum()
                
                area_total = area_ocupacion + area_patios
            else:
                from shapely.geometry import Polygon as ShapelyPolygon
                poly_ext = ShapelyPolygon(anillo_ext)
                factor_area = 1.23e10 if is_degrees else 1.0
                factor_perim = 1.11e5 if is_degrees else 1.0
                
                area_total = poly_ext.area * factor_area
                area_patios = sum(ShapelyPolygon(h).area for h in huecos) * factor_area
                area_ocupacion = area_total - area_patios
                perimetro = poly_ext.length * factor_perim

            return {
                "geometria_procesada": True,
                "area_geometrica_m2": round(area_total, 2),
                "area_patios_m2": round(area_patios, 2),
                "area_ocupacion_geometrica_m2": round(area_ocupacion, 2),
                "perimetro_m": round(perimetro, 2),
                "numero_anillos": len(geometria_anillos),
                "forma_parcela": self._determinar_forma_parcela(ShapelyPolygon(anillo_ext)),
                "factor_forma": round(area_ocupacion / (perimetro ** 2), 4) if perimetro > 0 else 0,
                "is_degrees": is_degrees
            }
        except Exception as e:
            return {"error": f"Error procesando geometría: {str(e)}"}
    
    def _procesar_datos_sede(self, datos_sede: Dict) -> Dict[str, Any]:
        """
        Procesa datos de la sede para enriquecer el análisis
        """
        try:
            return {
                "datos_sede_procesados": True,
                "uso_principal_sede": datos_sede.get('uso', 'Residencial'),
                "tipo_construccion": datos_sede.get('tipo_construccion', 'Bloque'),
                "estado_conservacion": datos_sede.get('estado', 'Bueno'),
                "ano_construccion_sede": datos_sede.get('ano_construccion', 2000),
                "numero_viviendas": datos_sede.get('numero_viviendas', 1),
                "superficie_util_m2": datos_sede.get('superficie_util', 150),
                "coeficiente_eficiencia": self._calcular_eficiencia(datos_sede)
            }
        except Exception as e:
            return {"error": f"Error procesando datos de sede: {str(e)}"}
    
    def _cruzar_registro_propiedad(self, datos_registro: Dict, datos_parcela: Dict) -> Dict[str, Any]:
        """
        Cruza datos del Registro de la Propiedad con datos catastrales
        """
        try:
            superficie_registral = float(datos_registro.get('superficie_registral', 0))
            superficie_catastral = datos_parcela.get('superficie_terreno', 0)
            
            if superficie_registral <= 0:
                return {"error": "Superficie registral no válida"}
            
            diferencia = superficie_catastral - superficie_registral
            desvio_porcentual = (diferencia / superficie_registral) * 100 if superficie_registral > 0 else 0
            coordinacion_posible = abs(desvio_porcentual) <= 10.0
            
            return {
                "cruce_registro_realizado": True,
                "superficie_registral_m2": round(superficie_registral, 2),
                "superficie_catastral_m2": round(superficie_catastral, 2),
                "diferencia_m2": round(diferencia, 2),
                "desvio_porcentual": round(desvio_porcentual, 2),
                "coordinacion_posible": coordinacion_posible,
                "nivel_concordancia": self._determinar_nivel_concordancia(desvio_porcentual),
                "recomendacion": self._generar_recomendacion_cruce(desvio_porcentual, coordinacion_posible)
            }
        except Exception as e:
            return {"error": f"Error en cruce con registro: {str(e)}"}
    
    def _determinar_forma_parcela(self, polygon: Polygon) -> str:
        """
        Determina la forma de la parcela basada en su geometría
        """
        try:
            area = polygon.area
            perimetro = polygon.length
            if perimetro == 0: return "Indeterminada"
            factor_forma = area / (perimetro ** 2)
            if factor_forma > 0.06: return "Regular/Cuadrada"
            elif factor_forma > 0.04: return "Rectangular"
            elif factor_forma > 0.02: return "Irregular"
            else: return "Muy irregular"
        except:
            return "No determinable"
    
    def _calcular_eficiencia(self, datos_sede: Dict) -> float:
        """
        Calcula coeficiente de eficiencia de la construcción
        """
        try:
            superficie_util = float(datos_sede.get('superficie_util', 150))
            superficie_construida = float(datos_sede.get('superficie_construida', 180))
            if superficie_construida > 0:
                return round(superficie_util / superficie_construida, 3)
            return 0.0
        except:
            return 0.0
    
    def _determinar_nivel_concordancia(self, desvio_porcentual: float) -> str:
        """
        Determina el nivel de concordancia entre catastro y registro
        """
        abs_desvio = abs(desvio_porcentual)
        if abs_desvio <= 5: return "Muy alta"
        elif abs_desvio <= 10: return "Alta"
        elif abs_desvio <= 20: return "Media"
        elif abs_desvio <= 30: return "Baja"
        else: return "Muy baja"
    
    def _generar_recomendacion_cruce(self, desvio_porcentual: float, coordinacion_posible: bool) -> str:
        """
        Genera recomendación basada en el cruce de datos
        """
        abs_desvio = abs(desvio_porcentual)
        if coordinacion_posible:
            return "Coordinación catastral-registral posible. Desviación dentro de límites legales."
        elif abs_desvio <= 20:
            return "Se recomienda verificar mediciones y posible rectificación."
        else:
            return "Desviación significativa. Requiere intervención técnica y posible procedimiento de rectificación."


# Función de compatibilidad con el código existente
def realizar_analisis_urbanistico(geometria_anillos, datos_sede=None, datos_registro=None):
    """
    Función de compatibilidad para el código existente que delega en el InformeUrbanistico
    """
    generador = InformeUrbanistico()
    res = generador._procesar_geometria_anillos(geometria_anillos)
    
    if "error" in res:
        return res

    return {
        "superficie_parcela_m2": res["area_geometrica_m2"],
        "superficie_ocupada_m2": res["area_ocupacion_geometrica_m2"],
        "superficie_patios_m2": res["area_patios_m2"],
        "edificabilidad_estimada_m2": round(res["area_geometrica_m2"] * 0.6, 2),
        "porcentaje_ocupacion": round((res["area_ocupacion_geometrica_m2"] / res["area_geometrica_m2"]) * 100, 2) if res["area_geometrica_m2"] > 0 else 0,
        "uso_principal": datos_sede.get('uso', 'Residencial') if datos_sede else "Consultar Sede",
        "cruce_registro": {}
    }
