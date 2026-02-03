#!/usr/bin/env python3
"""
Script para diagnosticar el proceso de descarga
"""

import sys
import os
from pathlib import Path

# Añadir el directorio actual al path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

try:
    from catastro4 import CatastroDownloader, procesar_y_comprimir
    print("✅ Módulo catastro4 importado correctamente")
except ImportError as e:
    print(f"❌ Error importando catastro4: {e}")
    sys.exit(1)

def test_descarga_individual():
    """Prueba de descarga individual"""
    print("\n" + "="*60)
    print("🧪 PRUEBA DE DESCARGA INDIVIDUAL")
    print("="*60)
    
    # Referencia de prueba
    ref = "2289738XH6028N0001RY"
    
    try:
        # Crear directorio de salida
        output_dir = Path("test_outputs")
        output_dir.mkdir(exist_ok=True)
        
        # Crear descargador
        downloader = CatastroDownloader(output_dir=str(output_dir))
        print(f"✅ Descargador creado en: {output_dir}")
        
        # Probar obtener coordenadas
        print(f"\n📍 Probando obtener coordenadas para {ref}...")
        coords = downloader.obtener_coordenadas_unificado(ref)
        if coords:
            print(f"✅ Coordenadas obtenidas: {coords}")
        else:
            print(f"❌ No se pudieron obtener coordenadas")
            return False
        
        # Probar descargar GML
        print(f"\n📄 Probando descargar GML para {ref}...")
        gml_descargado = downloader.descargar_parcela_gml(ref)
        if gml_descargado:
            print(f"✅ GML descargado correctamente")
        else:
            print(f"❌ No se pudo descargar GML")
            return False
        
        # Verificar archivo GML
        gml_file = output_dir / ref / f"{ref}_parcela.gml"
        if gml_file.exists():
            print(f"✅ Archivo GML existe: {gml_file}")
            print(f"📏 Tamaño: {gml_file.stat().st_size} bytes")
        else:
            print(f"❌ Archivo GML no encontrado: {gml_file}")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ Error en prueba individual: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_proceso_completo():
    """Prueba del proceso completo"""
    print("\n" + "="*60)
    print("🧪 PRUEBA DE PROCESO COMPLETO")
    print("="*60)
    
    # Referencia de prueba
    ref = "2289738XH6028N0001RY"
    
    try:
        # Directorio de salida
        output_dir = Path("test_completo")
        
        print(f"\n🚀 Iniciando proceso completo para {ref}...")
        zip_path, resultados = procesar_y_comprimir(
            referencia=ref,
            directorio_base=str(output_dir)
        )
        
        print(f"\n📊 Resultados:")
        for key, value in resultados.items():
            print(f"  {key}: {value}")
        
        if zip_path:
            print(f"\n✅ ZIP generado: {zip_path}")
            if Path(zip_path).exists():
                print(f"📏 Tamaño ZIP: {Path(zip_path).stat().st_size / (1024*1024):.2f} MB")
            else:
                print(f"❌ Archivo ZIP no encontrado: {zip_path}")
        else:
            print(f"❌ No se generó ZIP")
        
        return resultados.get('exitosa', False)
        
    except Exception as e:
        print(f"❌ Error en proceso completo: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Función principal"""
    print("🔍 DIAGNÓSTICO DEL PROCESO DE DESCARGA CATASTRO")
    print("="*60)
    
    # Verificar dependencias
    print("\n📦 Verificando dependencias...")
    try:
        import requests
        print("✅ requests disponible")
    except ImportError:
        print("❌ requests no disponible")
    
    try:
        import zipfile
        print("✅ zipfile disponible")
    except ImportError:
        print("❌ zipfile no disponible")
    
    try:
        from PIL import Image
        print("✅ PIL disponible")
    except ImportError:
        print("⚠️ PIL no disponible (opcional)")
    
    try:
        from reportlab.pdfgen import canvas
        print("✅ ReportLab disponible")
    except ImportError:
        print("⚠️ ReportLab no disponible (opcional)")
    
    # Ejecutar pruebas
    success_individual = test_descarga_individual()
    success_completo = test_proceso_completo()
    
    # Resumen final
    print("\n" + "="*60)
    print("📋 RESUMEN FINAL")
    print("="*60)
    print(f"Prueba individual: {'✅ ÉXITO' if success_individual else '❌ FALLO'}")
    print(f"Proceso completo: {'✅ ÉXITO' if success_completo else '❌ FALLO'}")
    
    if success_individual and success_completo:
        print("\n🎉 Todas las pruebas pasaron correctamente")
    else:
        print("\n⚠️ Hay problemas en el proceso de descarga")

if __name__ == "__main__":
    main()
