#!/usr/bin/env python3
"""
Script para limpiar archivos no necesarios del proyecto
"""

import os
import shutil

# Archivos esenciales que NO deben eliminarse
ESSENCIALES = {
    # Principal
    'main.py',
    'catastro4.py',
    'urbanismo.py', 
    'afecciones.py',
    
    # Configuración
    'config.json',
    'config_web.json',
    'mapa_municipios.json',
    'requirements.txt',
    
    # Frontend
    'static/visor.html',
    'static/estilos_base.css',
    
    # Servidores útiles
    'iniciar_nuevo_visor.py',
    'servidor_final.py',
    
    # Cache y datos
    'catastro_cache.sqlite',
    'outputs/',
    'descargas/',
    'descargas_catastro/',
    'referenciaspy/',
    'plantillas/',
    'iconos/',
    'static/',
    'build/',
    'dist/',
    '__pycache__/',
    '.vscode/',
    '.github/'
}

def eliminar_archivos_no_necesarios():
    """Eliminar archivos que no son esenciales"""
    
    # Archivos a eliminar
    archivos_a_eliminar = [
        # Documentación
        'ARCHIVOS_DESCARGADOS.md',
        'ARQUITECTURA.txt', 
        'COMPLETADO.txt',
        'EJEMPLOS_DE_USO.py',
        'ERRORES_CORREGIDOS.txt',
        'ESTADO_FINAL.txt',
        'ESTADO_INTEGRACION.txt',
        'ESTRUCTURA_BOTONES.md',
        'FIXES_COMPLETED.md',
        'FUNCIONES_BOTONES_DETALLADAS.py',
        'GUIA_RAPIDA_DESCARGAS.md',
        'GUIA_USO.txt',
        'INDEX.md',
        'INICIAR_VISOR.bat',
        'INICIO_RAPIDO.txt',
        'INTEGRACION_FUNCIONES_REFERENCIASPY.md',
        'INTEGRACION_REFERENCIASPY.md',
        'INTEGRACION_VISOR.md',
        'LEEME.txt',
        'LISTA_DE_CAMBIOS.md',
        'README.txt',
        'README_INTEGRACION_COMPLETA.md',
        'README_VISOR.md',
        'README_WEB6.md',
        'RESUMEN_EJECUTIVO.md',
        'RESUMEN_FINAL.txt',
        'RESUMEN_INTEGRACION.md',
        'RESUMEN_INTEGRACION_FINAL.md',
        'RESUMEN_TECNICO.md',
        'RESUMEN_VISUAL_INTEGRACION.txt',
        'STATUS.txt',
        'VERIFICACION_INTEGRACION.md',
        'estructura.txt',
        'lanzar.txt',
        
        # Scripts de prueba
        'check_syntax.py',
        'probar_app.py',
        'simple_server.py',
        'test_*.py',
        'run_server.py',
        'servidor_corregido.py',
        'start_server.bat',
        'iniciar_servidor.bat',
        'servidor_simple.bat',
        'lanzar.bat',
        
        # Versiones antiguas
        'main_fixed.py',
        'main_complete.py',
        'main_visor_integrado.py',
        'visor_functions.py',
        'visor_functions_complete.py',
        'visor_functions_integrated.py',
        
        # Build y ejecutables
        'build_exe.py',
        'GeneradorCatastral.spec',
        'GeneradorCatastral_Portable/',
        'GeneradorCatastral_Portable.zip',
        
        # Archivos temporales
        'deepseek_*.py',
        'deepseek_*.txt',
        'icon.ico',
        'mapa_parcelas.py',
        'demo.html',
        'test_descarga_completa.py',
        'test_endpoints.py',
        'test_imports.py',
        'test_referenciaspy_integration.py',
        'test_simple.py',
        'test_app.py'
    ]
    
    eliminados = 0
    errores = []
    
    print("🧹 LIMPIEZA DE ARCHIVOS NO NECESARIOS")
    print("=" * 50)
    
    # Eliminar archivos específicos
    for patron in archivos_a_eliminar:
        if '*' in patron:
            # Usar glob para patrones con comodines
            import glob
            archivos = glob.glob(patron)
            for archivo in archivos:
                try:
                    if os.path.isfile(archivo):
                        os.remove(archivo)
                        print(f"✅ Eliminado: {archivo}")
                        eliminados += 1
                    elif os.path.isdir(archivo):
                        shutil.rmtree(archivo)
                        print(f"✅ Eliminado directorio: {archivo}")
                        eliminados += 1
                except Exception as e:
                    errores.append(f"❌ Error eliminando {archivo}: {e}")
        else:
            # Eliminar archivo específico
            if os.path.exists(patron):
                try:
                    if os.path.isfile(patron):
                        os.remove(patron)
                        print(f"✅ Eliminado: {patron}")
                        eliminados += 1
                    elif os.path.isdir(patron):
                        shutil.rmtree(patron)
                        print(f"✅ Eliminado directorio: {patron}")
                        eliminados += 1
                except Exception as e:
                    errores.append(f"❌ Error eliminando {patron}: {e}")
    
    print("=" * 50)
    print(f"📊 Resumen:")
    print(f"   ✅ Archivos eliminados: {eliminados}")
    print(f"   ❌ Errores: {len(errores)}")
    
    if errores:
        print("\n🚨 Errores encontrados:")
        for error in errores:
            print(f"   {error}")
    
    print(f"\n📁 Archivos esenciales conservados:")
    for esencial in sorted(ESSENCIALES):
        print(f"   ✅ {esencial}")
    
    return eliminados, len(errores)

if __name__ == "__main__":
    eliminar_archivos_no_necesarios()
