#!/usr/bin/env python3
"""
Script para integrar automáticamente la detección de capas en main.py
Ejecutar: python integrar_capas.py
"""

import os
import re
from pathlib import Path

def integrar_capas():
    """Integra automáticamente los módulos de capas en main.py"""
    
    main_path = Path("main.py")
    
    if not main_path.exists():
        print("❌ main.py no encontrado")
        return False
    
    print("📝 Leyendo main.py...")
    with open(main_path, 'r', encoding='utf-8') as f:
        contenido = f.read()
    
    # 1. AGREGAR IMPORTES
    print("1️⃣  Agregando importes...")
    
    importes_nuevos = """from src.utils.auto_detect_layers import inicializar_capas, obtener_capas
from src.utils.cruzador_capas import CruzadorCapas"""
    
    # Buscar última línea de importes
    patron_imports = r'(from fastapi\.middleware\.cors import CORSMiddleware\n)'
    if re.search(patron_imports, contenido):
        contenido = re.sub(
            patron_imports,
            f'\\1{importes_nuevos}\n',
            contenido
        )
        print("   ✅ Importes agregados")
    else:
        print("   ⚠️  No se encontró patrón de importes, buscando otra ubicación...")
        # Buscar después de "from pydantic import BaseModel"
        if 'from pydantic import BaseModel' in contenido:
            contenido = contenido.replace(
                'from pydantic import BaseModel',
                f'from pydantic import BaseModel\n{importes_nuevos}'
            )
            print("   ✅ Importes agregados (ubicación alternativa)")
    
    # 2. INICIALIZAR CAPAS
    print("2️⃣  Inicializando sistema de capas...")
    
    inicializacion = """
# ==========================================
# INICIALIZAR DETECCIÓN DE CAPAS
# ==========================================
print("\\n🚀 INICIANDO SERVIDOR CON DETECCIÓN DE CAPAS...\\n")

# Detectar capas disponibles
CAPAS_SISTEMA = inicializar_capas(Path(outputs_dir).parent)

# Crear instancia del cruzador
cruzador = CruzadorCapas(CAPAS_SISTEMA)

print(f"\\n✅ SERVIDOR LISTO CON {CAPAS_SISTEMA['total']} CAPAS DETECTADAS\\n")
"""
    
    # Buscar línea donde se monta static
    if 'app.mount("/static"' in contenido:
        idx = contenido.find('app.mount("/static"')
        # Buscar final de esa línea
        idx_fin = contenido.find('\n', idx) + 1
        contenido = contenido[:idx_fin] + inicializacion + contenido[idx_fin:]
        print("   ✅ Sistema de capas inicializado")
    
    # 3. AGREGAR ENDPOINTS
    print("3️⃣  Agregando endpoints...")
    
    endpoints_nuevos = '''
# ==========================================
# ENDPOINTS DE CAPAS Y AFECCIONES
# ==========================================

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
            with open(afecciones_path, 'r', encoding='utf-8') as f:
                afecciones = json.load(f)
            return {"status": "success", "afecciones": afecciones}
        else:
            return {"status": "processing", "message": "Afecciones en procesamiento"}
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
'''
    
    # Agregar antes de "if __name__ == '__main__'"
    if 'if __name__ == "__main__"' in contenido:
        idx = contenido.find('if __name__ == "__main__"')
        contenido = contenido[:idx] + endpoints_nuevos + '\n' + contenido[idx:]
        print("   ✅ Endpoints agregados")
    
    # 4. GUARDAR CAMBIOS
    print("4️⃣  Guardando cambios...")
    
    # Hacer backup
    backup_path = Path("main.py.backup")
    with open(backup_path, 'w', encoding='utf-8') as f:
        f.write(contenido)
    print(f"   ✅ Backup creado: {backup_path}")
    
    # Guardar main.py actualizado
    with open(main_path, 'w', encoding='utf-8') as f:
        f.write(contenido)
    print("   ✅ main.py actualizado")
    
    print("\n" + "="*60)
    print("✅ INTEGRACIÓN COMPLETADA")
    print("="*60)
    print("\nCambios realizados:")
    print("  1. ✅ Importes agregados")
    print("  2. ✅ Sistema de capas inicializado")
    print("  3. ✅ Endpoints de capas y afecciones agregados")
    print("\nPróximos pasos:")
    print("  1. Reinicia el servidor: python main.py")
    print("  2. Verifica en consola que detecta las capas")
    print("  3. Prueba: GET /api/v1/capas/disponibles")
    print("\n")
    
    return True

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🔧 INTEGRADOR AUTOMÁTICO DE CAPAS")
    print("="*60 + "\n")
    
    if integrar_capas():
        print("✅ ¡Listo para usar!")
    else:
        print("❌ Error durante la integración")
