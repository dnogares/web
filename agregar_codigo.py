#!/usr/bin/env python3
import os
from pathlib import Path

os.chdir(Path(__file__).parent)

print("📝 AGREGANDO CÓDIGO A main.py\n")

# Leer main.py actual
with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

# El código a agregar
nuevo_codigo = '''
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
    """Retorna lista de todas las capas disponibles"""
    capas = obtener_capas()
    return {
        "status": "success",
        "total": capas['total'],
        "por_tipo": capas['por_tipo'],
        "capas": capas['capas']
    }

@app.get("/api/v1/expedientes/{expediente_id}/afecciones")
async def obtener_afecciones_expediente(expediente_id: str):
    """Obtiene las afecciones detectadas para un expediente"""
    try:
        exp_dir = Path(outputs_dir) / "expedientes" / f"expediente_{expediente_id}"
        afecciones_path = exp_dir / "afecciones.json"
        
        if afecciones_path.exists():
            with open(afecciones_path, "r", encoding="utf-8") as f:
                afecciones = json.load(f)
            return {"status": "success", "afecciones": afecciones}
        else:
            return {"status": "processing", "message": "Afecciones en procesamiento"}
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


'''

# Buscar if __name__ == "__main__"
if_main = 'if __name__ == "__main__":'
idx = content.find(if_main)

if idx == -1:
    print("❌ No se encontró 'if __name__ == \"__main__\":'")
    print("\nBuscando alternativas...")
    if 'if __name__' in content:
        print("⚠️  Encontré 'if __name__' pero con formato diferente")
    exit(1)

# Insertar código ANTES de if __name__
new_content = content[:idx] + nuevo_codigo + content[idx:]

# Guardar
with open("main.py", "w", encoding="utf-8") as f:
    f.write(new_content)

num_linea = content[:idx].count('\n') + 1

print("✅ Código agregado correctamente!")
print(f"   Ubicación: Línea ~{num_linea}")
print(f"   Líneas agregadas: ~35")
print(f"\n📊 Estadísticas:")
print(f"   • Líneas anteriores: {len(content.split(chr(10)))}")
print(f"   • Líneas nuevas: {len(new_content.split(chr(10)))}")

print("\n" + "="*60)
print("✅ LISTO PARA PROBAR")
print("="*60)
print("\nEjecuta:")
print("  python main.py")
print("\nDeberías ver:")
print("  🚀 INICIANDO SERVIDOR CON DETECCIÓN DE CAPAS...")
print("  🔍 DETECTANDO CAPAS DISPONIBLES...")
print("  ✅ SERVIDOR LISTO CON XX CAPAS DETECTADAS")
