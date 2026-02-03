"""
Wrapper para visor_functions_integrated
Módulo de compatibilidad para mantener la funcionalidad del visor
"""

# Importar desde la ubicación correcta si existe
try:
    from js.visor_logic_v3 import get_visor
    VISOR_FUNCTIONS_AVAILABLE = True
except ImportError:
    try:
        # Fallback a funciones básicas si no está disponible
        def get_visor():
            return {
                'status': 'limited',
                'message': 'Funciones básicas del visor disponibles'
            }
        VISOR_FUNCTIONS_AVAILABLE = True
    except ImportError:
        VISOR_FUNCTIONS_AVAILABLE = False

__all__ = ['get_visor', 'VISOR_FUNCTIONS_AVAILABLE']
