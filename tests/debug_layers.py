from pathlib import Path
import os

print("--- DIAGNÓSTICO DE CAPAS ---")
cwd = os.getcwd()
print(f"Directorio actual: {cwd}")

layers_dir = Path("capas")
if not layers_dir.exists():
    print("❌ Carpeta 'capas' no existe!")
    exit()

nombres_a_buscar = {
    "caminos": ["CCNN", "ETAPAS", "caminos"],
    "natura": ["PS.RNATURA2000", "RNATURA"],
}

for capa, keywords in nombres_a_buscar.items():
    print(f"\n🔍 Buscando capa: {capa} (Keywords: {keywords})")
    encontrado = False
    
    # Simulación de la lógica de main.py
    archivos_candidatos = []
    
    # Búsqueda por archivo
    for nombre in keywords:
        patrones = [f"*{nombre}*.shp", f"*{nombre}*.geojson"]
        for patron in patrones:
            encontrados = list(layers_dir.rglob(patron))
            archivos_candidatos.extend(encontrados)
            if encontrados:
                print(f"  Found by file name '{patron}': {[str(f) for f in encontrados]}")

    # Búsqueda por carpeta
    if not archivos_candidatos:
         print("  No encontrado por nombre, buscando en carpetas...")
         for nombre in keywords:
             carpetas = list(layers_dir.rglob(f"*{nombre}*"))
             for d in carpetas:
                 if d.is_dir():
                     print(f"  Carpeta candidata: {d}")
                     files = list(d.rglob("*.shp")) + list(d.rglob("*.geojson"))
                     if files:
                         print(f"  Archivos dentro: {[str(f) for f in files]}")
                         archivos_candidatos.extend(files)

    if archivos_candidatos:
        print(f"✅ CANDIDATOS FINALES PARA {capa}:")
        for f in archivos_candidatos:
             print(f"   -> {f} (Size: {f.stat().st_size / 1024 / 1024:.2f} MB)")
    else:
        print(f"❌ NO SE ENCONTRÓ NADA PARA {capa}")
