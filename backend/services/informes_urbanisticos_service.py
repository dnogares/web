#!/usr/bin/env python3
"""
Servicio de Informes Urbanísticos
"""

import json
import os
from typing import Dict, Any, Optional
from shapely.geometry import Polygon


class InformeUrbanistico:
    """Clase principal para generar informes urbanísticos"""
    
    def __init__(self, config_file: str = "urbanismo_config.json"):
        """
        Inicializa el generador de informes
        """
        self.config_file = config_file
        self.config = self._cargar_configuracion()
    
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
                                municipio: str = None, via: str = None, numero: str = None) -> Dict[str, Any]:
        """
        Genera un informe urbanístico completo
        """
        try:
            # Simulación de obtención de datos (en producción vendría de APIs externas)
            datos_parcela = self._obtener_datos_parcela(ref_catastral, provincia, municipio, via, numero)
            analisis_tecnico = self._realizar_analisis_tecnico(datos_parcela)
            clasificacion_suelo = self._obtener_clasificacion_suelo(datos_parcela)
            afecciones = self._analizar_afecciones_territoriales(datos_parcela)
            
            return {
                "referencia_catastral": ref_catastral,
                "direccion": f"{via} {numero}, {municipio}, {provincia}" if via and numero else "Sin especificar",
                "datos_parcela": datos_parcela,
                "clasificacion_suelo": clasificacion_suelo,
                "analisis_tecnico": analisis_tecnico,
                "afecciones_territoriales": afecciones,
                "fecha_informe": self._get_fecha_actual()
            }
            
        except Exception as e:
            return {
                "error": f"Error generando informe: {str(e)}",
                "referencia_catastral": ref_catastral
            }
    
    def _obtener_datos_parcela(self, ref_catastral: str = None, provincia: str = None, 
                              municipio: str = None, via: str = None, numero: str = None) -> Dict[str, Any]:
        """
        Obtiene datos de la parcela (simulado)
        """
        # Simulación de datos catastrales
        return {
            "superficie_terreno": 850,
            "superficie_construida": 180,
            "uso_principal": "residencial",
            "ano_construccion": 1998,
            "estado_conservacion": "Bueno",
            "numero_plantas": 3,
            "coordenadas": [-4.4250, 36.7200]  # Coordenadas Málaga
        }
    
    def _realizar_analisis_tecnico(self, datos_parcela: Dict[str, Any]) -> Dict[str, Any]:
        """
        Realiza el análisis técnico de la parcela
        """
        uso = datos_parcela.get('uso_principal', 'residencial')
        coef = self.config['coeficientes_edificabilidad'].get(uso, 0.6)
        
        sup_terreno = datos_parcela.get('superficie_terreno', 0)
        sup_construida = datos_parcela.get('superficie_construida', 0)
        
        edificabilidad_maxima = sup_terreno * coef
        edificabilidad_actual = sup_construida
        edificabilidad_disponible = edificabilidad_maxima - edificabilidad_actual
        
        return {
            "superficie_terreno_m2": sup_terreno,
            "superficie_construida_m2": sup_construida,
            "edificabilidad_maxima_m2": round(edificabilidad_maxima, 2),
            "edificabilidad_actual_m2": edificabilidad_actual,
            "edificabilidad_disponible_m2": round(max(0, edificabilidad_disponible), 2),
            "coeficiente_edificabilidad": coef,
            "porcentaje_ocupacion": round((sup_construida / sup_terreno) * 100, 2) if sup_terreno > 0 else 0
        }
    
    def _obtener_clasificacion_suelo(self, datos_parcela: Dict[str, Any]) -> Dict[str, Any]:
        """
        Obtiene la clasificación del suelo
        """
        # Simulación según coordenadas y uso
        return {
            "clasificacion": "Suelo Urbano",
            "calificacion": "Residencial Consolidado",
            "uso_principal": self.config['usos_principales'].get(datos_parcela.get('uso_principal', 'residencial'), 'Vivienda'),
            "densidad_edificatoria": "Media",
            "ordenanza": "Plan General Municipal",
            "zona": "Centro Urbano"
        }
    
    def _analizar_afecciones_territoriales(self, datos_parcela: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analiza las afecciones territoriales
        """
        afecciones = self.config['afecciones_territoriales']
        
        # Simulación de afecciones (en producción vendría de cruce con capas geográficas)
        afecciones_detectadas = {}
        
        for afeccion in afecciones:
            # Simulación aleatoria de afecciones
            import random
            afectado = random.choice([True, False, False])  # 33% probabilidad
            afecciones_detectadas[afeccion] = afectado
        
        return afecciones_detectadas
    
    def _get_fecha_actual(self) -> str:
        """
        Obtiene la fecha actual formateada
        """
        from datetime import datetime
        return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


# Función de compatibilidad con el código existente
def realizar_analisis_urbanistico(geometria_anillos, datos_sede=None, datos_registro=None):
    """
    Función de compatibilidad para el código existente
    """
    if not geometria_anillos or not isinstance(geometria_anillos, list):
        return {"error": "Geometría no válida"}

    # El primer anillo es el exterior, los demás son patios
    poly_exterior = Polygon(geometria_anillos[0])
    patios = [Polygon(p) for p in geometria_anillos[1:]]
    
    area_total = poly_exterior.area * 10**10 # Ajuste escala (según CRS)
    area_patios = sum(p.area * 10**10 for p in patios)
    area_ocupacion = area_total - area_patios
    
    # Simulación de coeficiente (esto debería venir de normativa local)
    coeficiente_estimado = 0.6 
    edificabilidad_maxima = area_total * coeficiente_estimado

    # Cruce con Registro de la Propiedad (si hay datos)
    analisis_registro = {}
    if datos_registro and 'superficie_registral' in datos_registro:
        try:
            sup_reg = float(datos_registro['superficie_registral'])
            diferencia = area_total - sup_reg
            desvio = (diferencia / sup_reg) * 100 if sup_reg > 0 else 0
            
            analisis_registro = {
                "superficie_registral_m2": round(sup_reg, 2),
                "diferencia_m2": round(diferencia, 2),
                "desvio_porcentaje": round(desvio, 2),
                "coordinacion_posible": abs(desvio) <= 10.0  # Tolerancia del 10% (Ley 13/2015)
            }
        except (ValueError, TypeError):
            analisis_registro = {"error": "Datos registrales inválidos"}

    return {
        "superficie_parcela_m2": round(area_total, 2),
        "superficie_ocupada_m2": round(area_ocupacion, 2),
        "superficie_patios_m2": round(area_patios, 2),
        "edificabilidad_estimada_m2": round(edificabilidad_maxima, 2),
        "porcentaje_ocupacion": round((area_ocupacion / area_total) * 100, 2) if area_total > 0 else 0,
        "uso_principal": datos_sede.get('uso', 'Residencial') if datos_sede else "Consultar Sede",
        "cruce_registro": analisis_registro
    }
