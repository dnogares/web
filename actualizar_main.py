import os
import sys
from pathlib import Path

# Cambiar a directorio del proyecto
os.chdir(Path(__file__).parent)

# Leer main.py
main_path = Path("main.py")
with open(main_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Buscar línea de importes FastAPI
insert_imports_idx = None
for i, line in enumerate(lines):
    if 'from fastapi.middleware.cors import CORSMiddleware' in line:
        insert_imports_idx = i + 1
        break

if insert_imports_idx:
    # Insertar importes nuevos
    new_imports = [
        'from src.utils.auto_detect_layers import inicializar_capas, obtener_capas\n',
        'from src.utils.cruzador_capas import CruzadorCapas\n'
    ]
    lines = lines[:insert_imports_idx] + new_imports + lines[insert_imports_idx:]
    print("✅ Importes agregados")

# Buscar línea "app.mount("/static"" para inicializar capas
init_idx = None
for i, line in enumerate(lines):
    if 'app.mount("/static"' in line:
        # Buscar final de statement
        while i < len(lines) and not lines[i].strip().endswith(')'):
            i += 1
        init_idx = i + 1
        break

if init_idx:
    init_code = [
        '\n',
        '# ==========================================\n',
        '# INICIALIZAR DETECCIÓN DE CAPAS\n',
        '# ==========================================\n',
        'print("\\n🚀 INICIANDO SERVIDOR CON DETECCIÓN DE CAPAS...\\n")\n',
        '\n',
        'CAPAS_SISTEMA = inicializar_capas(Path(outputs_dir).parent)\n',
        'cruzador = CruzadorCapas(CAPAS_SISTEMA)\n',
        '\n',
        'print(f"\\n✅ SERVIDOR LISTO CON {CAPAS_SISTEMA[\'total\']} CAPAS DETECTADAS\\n")\n',
    ]
    lines = lines[:init_idx] + init_code + lines[init_idx:]
    print("✅ Inicialización de capas agregada")

# Agregar endpoints antes de if __name__
endpoints_idx = None
for i, line in enumerate(lines):
    if 'if __name__ == "__main__"' in line:
        endpoints_idx = i
        break

if endpoints_idx:
    endpoints_code = [
        '\n',
        '# ==========================================\n',
        '# ENDPOINTS DE CAPAS Y AFECCIONES\n',
        '# ==========================================\n',
        '\n',
        '@app.get("/api/v1/capas/disponibles")\n',
        'async def obtener_capas_disponibles():\n',
        '    """Retorna lista de todas las capas disponibles"""\n',
        '    capas = obtener_capas()\n',
        '    return {\n',
        '        "status": "success",\n',
        '        "total": capas["total"],\n',
        '        "por_tipo": capas["por_tipo"],\n',
        '        "capas": capas["capas"]\n',
        '    }\n',
        '\n',
        '@app.get("/api/v1/expedientes/{expediente_id}/afecciones")\n',
        'async def obtener_afecciones_expediente(expediente_id: str):\n',
        '    """Obtiene las afecciones detectadas para un expediente"""\n',
        '    try:\n',
        '        exp_dir = Path(outputs_dir) / "expedientes" / f"expediente_{expediente_id}"\n',
        '        afecciones_path = exp_dir / "afecciones.json"\n',
        '        \n',
        '        if afecciones_path.exists():\n',
        '            with open(afecciones_path, "r", encoding="utf-8") as f:\n',
        '                afecciones = json.load(f)\n',
        '            return {"status": "success", "afecciones": afecciones}\n',
        '        else:\n',
        '            return {"status": "processing", "message": "Afecciones en procesamiento"}\n',
        '            \n',
        '    except Exception as e:\n',
        '        raise HTTPException(status_code=500, detail=str(e))\n',
        '\n',
    ]
    lines = lines[:endpoints_idx] + endpoints_code + lines[endpoints_idx:]
    print("✅ Endpoints agregados")

# Guardar cambios
with open(main_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("\n✅ main.py actualizado correctamente!")
print("\nReinicia el servidor para que los cambios tomen efecto")
