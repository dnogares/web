"""
Módulo catastro4 - Wrapper para CatastroDownloader
"""

from referenciaspy.catastro_downloader import CatastroDownloader

def procesar_y_comprimir(referencia: str, directorio_base: str = None):
    """
    Procesa y comprime los datos de una referencia catastral.
    Wrapper para mantener compatibilidad con el código existente.
    """
    try:
        # Crear instancia del descargador
        output_dir = directorio_base or "outputs"
        downloader = CatastroDownloader(output_dir=output_dir)
        
        # Descargar toda la documentación
        resultados = downloader.descargar_todo(referencia)
        
        # Crear ZIP con los resultados
        import zipfile
        import os
        from pathlib import Path
        
        ref_dir = Path(output_dir) / referencia
        zip_path = Path(output_dir) / f"{referencia}.zip"
        
        if ref_dir.exists():
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in ref_dir.rglob('*'):
                    if file_path.is_file():
                        arc_path = file_path.relative_to(ref_dir)
                        zipf.write(file_path, arc_path)
            
            return str(zip_path), {"exitosa": True, "resultados": resultados}
        else:
            return None, {"exitosa": False, "error": "No se encontraron archivos"}
            
    except Exception as e:
        return None, {"exitosa": False, "error": str(e)}

# Exportar las funciones principales
__all__ = ['CatastroDownloader', 'procesar_y_comprimir']
