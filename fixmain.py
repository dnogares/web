#!/usr/bin/env python3
import sys
import os
from pathlib import Path

# Cambiar al directorio del script
os.chdir(Path(__file__).parent)

print("🔧 ARREGLANDO main.py...\n")

main_file = Path("main.py")

if not main_file.exists():
    print("❌ main.py no encontrado en directorio actual")
    print(f"Directorio actual: {Path.cwd()}")
    sys.exit(1)

print(f"📖 Leyendo: {main_file}")

# Leer el archivo
with open(main_file, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Total de líneas: {len(lines)}")

# Encontrar y eliminar la sección problemática
nueva_lineas = []
i = 0
while i < len(lines):
    line = lines[i]
    
    # Detectar inicio de la sección problemática
    if 'INICIANDO SERVIDOR CON DETECCIÓN' in line:
        print(f"❌ Encontrado error en línea {i+1}")
        
        # Saltar todas las líneas hasta encontrar if __name__ o @app que no sea indentado
        j = i
        while j < len(lines):
            if (lines[j].strip().startswith('if __name__') or 
                (lines[j].strip().startswith('@app.') and not lines[j].startswith('        '))):
                i = j - 1  # Retroceder una línea para que se agregue en el siguiente ciclo
                break
            j += 1
        else:
            i = j - 1
        
        i += 1
        continue
    
    nueva_lineas.append(line)
    i += 1

# Guardar
print(f"💾 Guardando {len(nueva_lineas)} líneas...")
with open(main_file, 'w', encoding='utf-8') as f:
    f.writelines(nueva_lineas)

print("✅ Archivo arreglado!")
print(f"\nResultado:")
print(f"  • Líneas originales: {len(lines)}")
print(f"  • Líneas eliminadas: {len(lines) - len(nueva_lineas)}")
print(f"  • Líneas finales: {len(nueva_lineas)}")

print("\n" + "="*60)
print("PRÓXIMAS INSTRUCCIONES:")
print("="*60)
print("""
1. Abre main.py con tu editor (VS Code, etc)
2. Ve al final del archivo (Ctrl+End)
3. Busca la línea: if __name__ == '__main__':
4. ANTES de esa línea, agrega esto:

# ==========================================
# INICIALIZAR DETECCIÓN DE CAPAS
# ==========================================

from src.utils.auto_detect_layers import inicializar_capas, obtener_capas
from src.utils.cruzador_capas import CruzadorCapas

print("\\n🚀 INICIANDO SERVIDOR CON DETECCIÓN DE CAPAS...\\n")
CAPAS_SISTEMA = inicializar_capas(Path(outputs_dir).parent)
cruzador = CruzadorCapas(CAPAS_SISTEMA)
print(f"\\n✅ SERVIDOR LISTO CON {CAPAS_SISTEMA['total']} CAPAS DETECTADAS\\n")

@app.get("/api/v1/capas/disponibles")
async def obtener_capas_disponibles():
    capas = obtener_capas()
    return {
        "status": "success",
        "total": capas['total'],
        "por_tipo": capas['por_tipo'],
        "capas": capas['capas']
    }

@app.get("/api/v1/expedientes/{expediente_id}/afecciones")
async def obtener_afecciones_expediente(expediente_id: str):
    try:
        exp_dir = Path(outputs_dir) / "expedientes" / f"expediente_{expediente_id}"
        afecciones_path = exp_dir / "afecciones.json"
        if afecciones_path.exists():
            with open(afecciones_path, "r", encoding="utf-8") as f:
                return {"status": "success", "afecciones": json.load(f)}
        return {"status": "processing"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

5. Guarda el archivo (Ctrl+S)
6. Prueba: python main.py
""")

print("\n✅ ¡Listo! El archivo está limpio")
