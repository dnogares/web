from gis_db import GISDatabase
import pandas as pd
import os

def test_db():
    print("🧪 Probando integración con base de datos GIS...")
    db = GISDatabase()
    
    if not db.test_connection():
        print("❌ Error: No se pudo conectar a la base de datos.")
        print("   Por favor, verifica las credenciales en config_web.json")
        return

    print("✅ Conexión establecida correctamente.")
    
    # Listar tablas disponibles
    layers = db.get_available_layers("afecciones")
    print(f"📊 Capas encontradas en esquema 'afecciones': {len(layers)}")
    if layers:
        print(f"   Primeras 5: {layers[:5]}")
    
    # Prueba de metadatos CSV
    csv_path = "datosdeGIS.csv"
    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
        csv_layers = df[df['table_schema'] == 'afecciones']['table_name'].unique()
        print(f"📄 Capas documentadas en CSV para 'afecciones': {len(csv_layers)}")
    else:
        print("⚠️ CSV de metadatos no encontrado.")

if __name__ == "__main__":
    test_db()
