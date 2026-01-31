"""
Script de prueba para ejecutar `procesar_y_comprimir` (procesarCatastro).
Ejecútalo en Powershell desde la raíz del proyecto:

python scripts/test_procesar.py 8884601WF4788S0020LL

Este script imprimirá el resultado o la traza de error para depuración.
"""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if len(sys.argv) < 2:
    print("Uso: python scripts/test_procesar.py <REFERENCIA>")
    sys.exit(1)

ref = sys.argv[1].strip()

try:
    from catastro4 import procesar_y_comprimir
    print(f"Iniciando procesar_y_comprimir para: {ref}")
    res = procesar_y_comprimir(ref, directorio_base='outputs', organize_by_type=False, generate_pdf=False, descargar_afecciones=False)
    print("Resultado:")
    print(res)
except Exception as e:
    print("Error durante la ejecución:")
    traceback.print_exc()
