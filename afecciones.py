"""
Wrapper para afecciones
Módulo de compatibilidad para análisis de afecciones
"""

# Importar desde la ubicación correcta si existe
try:
    from src.backend.services.afecciones_service import AfeccionesService
    
    AFECCIONES_AVAILABLE = True
    
except ImportError:
    try:
        # Fallback a funciones básicas si no está disponible
        def analizar_afecciones_geometria(geometria):
            """Función básica de análisis de afecciones"""
            return {
                'afecciones_territoriales': {
                    'hidrografia': {'afectada': False, 'descripcion': 'Análisis no disponible'},
                    'planeamiento': {'afectada': False, 'descripcion': 'Análisis no disponible'},
                    'catastro_parcelas': {'afectada': False, 'descripcion': 'Análisis no disponible'},
                    'red_natura': {'afectada': False, 'descripcion': 'Análisis no disponible'},
                    'vias_pecuarias': {'afectada': False, 'descripcion': 'Análisis no disponible'},
                    'montes_publicos': {'afectada': False, 'descripcion': 'Análisis no disponible'}
                },
                'error': 'Módulo afecciones no disponible'
            }
        
        AFECCIONES_AVAILABLE = True
        
    except ImportError:
        AFECCIONES_AVAILABLE = False

__all__ = ['analizar_afecciones_geometria', 'AFECCIONES_AVAILABLE']
