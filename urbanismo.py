import os
from shapely.geometry import Polygon

def realizar_analisis_urbanistico(geometria_anillos, datos_sede=None, datos_registro=None):
    """
    Analiza la geometría (anillos de Shapely) para obtener datos técnicos.
    Detecta automáticamente si las coordenadas están en grados o metros.
    """
    if not geometria_anillos or not isinstance(geometria_anillos, list):
        return {"error": "Geometría no válida"}

    # Intentar importar dependencias para cálculo preciso
    try:
        import geopandas as gpd
        from shapely.geometry import Polygon as ShapelyPolygon
        GEOPANDAS_AVAILABLE = True
    except ImportError:
        GEOPANDAS_AVAILABLE = False

    # El primer anillo es el exterior, los demás son patios
    anillo_exterior = geometria_anillos[0]
    patios_anillos = geometria_anillos[1:]

    # Detectar si las coordenadas están en grados (WGS84) o proyectadas (UTM)
    # Si los valores son pequeños (< 180), asumimos grados.
    sample_coord = anillo_exterior[0]
    is_degrees = abs(sample_coord[0]) < 180 and abs(sample_coord[1]) < 180 # Aumentado rango por si acaso

    if GEOPANDAS_AVAILABLE:
        # Usar GeoPandas para una transformación y cálculo precisos
        poly = ShapelyPolygon(anillo_exterior, patios_anillos)
        # Asumimos EPSG:4326 si son grados, o EPSG:25830 (UTM 30N) si son metros
        source_crs = "EPSG:4326" if is_degrees else "EPSG:25830"
        gdf = gpd.GeoDataFrame(geometry=[poly], crs=source_crs)
        
        # Convertir a UTM para cálculos de área si está en grados
        if is_degrees:
            gdf = gdf.to_crs(epsg=25830)
            
        area_total = gdf.geometry.area.iloc[0]
        
        # Calcular área de patios
        area_ocupacion = area_total 
        area_patios = 0
        if patios_anillos:
            patios_polys = [ShapelyPolygon(p) for p in patios_anillos]
            gdf_patios = gpd.GeoDataFrame(geometry=patios_polys, crs=source_crs)
            if is_degrees:
                gdf_patios = gdf_patios.to_crs(epsg=25830)
            area_patios = gdf_patios.geometry.area.sum()
            # El área del polígono con huecos ya es la ocupación real
            area_total = area_ocupacion + area_patios
    else:
        # Fallback si no hay GeoPandas
        poly_ext = Polygon(anillo_exterior)
        patios = [Polygon(p) for p in patios_anillos]
        
        # Multiplicador aproximado para grados a metros
        factor_area = 1.23e10 if is_degrees else 1.0
        
        area_total_raw = poly_ext.area
        area_patios_raw = sum(p.area for p in patios)
        
        area_total = area_total_raw * factor_area
        area_patios = area_patios_raw * factor_area
        area_ocupacion = area_total - area_patios

    # Simulación de coeficiente (esto debería venir de normativa local)
    coeficiente_estimado = 0.6 
    edificabilidad_maxima = area_total * coeficiente_estimado

    # Cruce con Registro de la Propiedad
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
                "coordinacion_posible": abs(desvio) <= 10.0
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
        "cruce_registro": analisis_registro,
        "metadatos_geometria": {
            "is_degrees": is_degrees,
            "precision": "GeoPandas" if GEOPANDAS_AVAILABLE else "Estimación"
        }
    }
