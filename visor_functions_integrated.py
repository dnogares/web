#!/usr/bin/env python3
"""
Funciones integradas para el visor catastral con Glassmorphism
"""

from fastapi.responses import HTMLResponse
from pathlib import Path

async def get_visor():
    """
    Función principal para obtener el visor catastral
    Retorna el HTML del visor con Glassmorphism
    """
    try:
        visor_path = Path("static/visor.html")
        
        if visor_path.exists():
            with open(visor_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            
            # Modificar el HTML si es necesario
            html_content = html_content.replace(
                '<title>Suite Tasación - Visor Pro</title>',
                '<title>Suite Tasación - Visor Pro (Integrado)</title>'
            )
            
            return HTMLResponse(content=html_content)
        else:
            # HTML por defecto si no existe el archivo
            html_default = """
            <!DOCTYPE html>
            <html lang="es">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Visor Catastral</title>
                <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
                <link rel="stylesheet" href="/static/estilos_base.css" />
                <style>
                    body { margin: 0; padding: 20px; font-family: Arial, sans-serif; }
                    .error { color: #e74c3c; background: #ffebee; padding: 20px; border-radius: 8px; }
                </style>
            </head>
            <body>
                <div class="error">
                    <h1>⚠️ Visor no encontrado</h1>
                    <p>No se pudo encontrar el archivo del visor en static/visor.html</p>
                    <p>Por favor, verifica que el archivo exista y sea accesible.</p>
                </div>
            </body>
            </html>
            """
            return HTMLResponse(content=html_default)
            
    except Exception as e:
        # HTML de error
        html_error = f"""
        <!DOCTYPE html>
        <html lang="es">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Error del Visor</title>
            <style>
                body {{ margin: 0; padding: 20px; font-family: Arial, sans-serif; }}
                .error {{ color: #e74c3c; background: #ffebee; padding: 20px; border-radius: 8px; }}
            </style>
        </head>
        <body>
            <div class="error">
                <h1>🚨 Error cargando el visor</h1>
                <p>Error: {str(e)}</p>
                <p>Por favor, contacta al administrador del sistema.</p>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html_error)

def get_map_layers():
    """
    Obtener configuración de capas para el mapa
    """
    return [
        {
            "name": "catastro",
            "title": "Catastro",
            "type": "wms",
            "url": "https://www.catastro.minhaf.es/INSPIRE/WFS",
            "visible": True,
            "opacity": 0.8
        },
        {
            "name": "ortofoto",
            "title": "Ortofoto",
            "type": "wms",
            "url": "https://www.ign.es/wms/pnoa",
            "visible": False,
            "opacity": 1.0
        },
        {
            "name": "natura",
            "title": "Red Natura 2000",
            "type": "wms",
            "url": "",
            "visible": False,
            "opacity": 0.7
        },
        {
            "name": "vias",
            "title": "Vías Pecuarias",
            "type": "wms",
            "url": "",
            "visible": False,
            "opacity": 0.7
        }
    ]

def get_measurement_tools():
    """
    Obtener configuración de herramientas de medición
    """
    return [
        {
            "name": "distance",
            "title": "Distancia",
            "icon": "📏",
            "color": "#3b82f6",
            "active": False
        },
        {
            "name": "area",
            "title": "Área",
            "icon": "📐",
            "color": "#10b981",
            "active": False
        },
        {
            "name": "clear",
            "title": "Limpiar",
            "icon": "🗑️",
            "color": "#ef4444",
            "active": False
        }
    ]

def get_navigation_items():
    """
    Obtener elementos de navegación del visor
    """
    return [
        {
            "id": "visor",
            "title": "Visor GIS",
            "icon": "🗺️",
            "active": True
        },
        {
            "id": "referencia",
            "title": "Referencia",
            "icon": "📍",
            "active": False
        },
        {
            "id": "analisis",
            "title": "Análisis",
            "icon": "⚙️",
            "active": False
        },
        {
            "id": "pdf",
            "title": "PDF",
            "icon": "📄",
            "active": False
        }
    ]

# Funciones de utilidad para el visor
def format_coordinates(lat, lon):
    """Formatear coordenadas para mostrar"""
    return f"{lat:.6f}, {lon:.6f}"

def calculate_area(points):
    """Calcular área de un polígono (aproximado)"""
    if len(points) < 3:
        return 0
    
    # Fórmula de Shoelace (aproximación simple)
    area = 0
    for i in range(len(points)):
        j = (i + 1) % len(points)
        area += points[i][0] * points[j][1]
        area -= points[j][0] * points[i][1]
    
    return abs(area) / 2

def calculate_distance(points):
    """Calcular distancia total de una línea (aproximado)"""
    if len(points) < 2:
        return 0
    
    total_distance = 0
    for i in range(len(points) - 1):
        # Distancia euclidiana simple (aproximación)
        dx = points[i+1][0] - points[i][0]
        dy = points[i+1][1] - points[i][1]
        total_distance += (dx**2 + dy**2)**0.5
    
    return total_distance
