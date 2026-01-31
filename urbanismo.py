import os
from shapely.geometry import Polygon

def realizar_analisis_urbanistico(geometria_anillos, datos_sede=None, datos_registro=None):
    """
    Analiza la geometría (anillos de Shapely) para obtener datos técnicos.
    Permite cruce con datos del Registro de la Propiedad si se proporcionan.
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
