"""
Wrapper para urbanismo
Módulo de compatibilidad para análisis urbanístico
"""

# Importar desde la ubicación correcta si existe
try:
    from src.backend.services.urbanismo_service import UrbanismoService
    from src.backend.services.urbanismo_service import realizar_analisis_urbanistico
    
    URBANISMO_AVAILABLE = True
    
except ImportError:
    try:
        # Fallback a funciones básicas si no está disponible
        def realizar_analisis_urbanistico(anillos):
            """Función básica de análisis urbanístico"""
            return {
                'clasificacion_suelo': {
                    'clasificacion': 'No determinado',
                    'calificacion': 'No determinado',
                    'uso_principal': 'No determinado',
                    'densidad_edificatoria': 'No determinado',
                    'ordenanza': 'No determinado',
                    'zona': 'No determinada'
                },
                'analisis_tecnico': {
                    'superficie_terreno_m2': 0,
                    'superficie_construida_m2': 0,
                    'edificabilidad_maxima_m2': 0,
                    'edificabilidad_actual_m2': 0,
                    'edificabilidad_disponible_m2': 0,
                    'coeficiente_edificabilidad': 0,
                    'porcentaje_ocupacion': 0
                },
                'error': 'Módulo urbanismo no disponible'
            }
        
        URBANISMO_AVAILABLE = True
        
    except ImportError:
        URBANISMO_AVAILABLE = False

__all__ = ['realizar_analisis_urbanistico', 'URBANISMO_AVAILABLE']
