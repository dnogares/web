#!/usr/bin/env python3
"""
Iniciar el nuevo visor catastral
"""

import http.server
import socketserver
import os
import sys

def main():
    PORT = 8000
    
    # Cambiar al directorio del script
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    print("🚀 INICIANDO NUEVO VISOR CATASTRAL")
    print("=" * 50)
    print(f"📁 Directorio: {os.getcwd()}")
    print(f"🌐 Puerto: {PORT}")
    print(f"🔗 URL: http://localhost:{PORT}")
    print(f"📋 Visor: http://localhost:{PORT}/static/visor_nuevo.html")
    print("=" * 50)
    print("✅ Nuevo diseño:")
    print("   - Panel izquierdo: Controles completos")
    print("   - Panel derecho: Mapa optimizado")
    print("   - Botones: Catastro, Urbanismo, Afecciones, PDF")
    print("   - Todo en una misma pantalla")
    print("⏹️ Presiona Ctrl+C para detener")
    print()
    
    try:
        with socketserver.TCPServer(('', PORT), http.server.SimpleHTTPRequestHandler) as httpd:
            print(f"✅ Servidor iniciado correctamente")
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Servidor detenido")
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
