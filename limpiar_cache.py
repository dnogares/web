import os
import sys

def limpiar_cache_catastro():
    """
    Busca y elimina el archivo de cache de catastro (catastro_cache.sqlite)
    para resolver errores de 'disk I/O error'.
    """
    # Asegurarse de que el script se ejecuta en el directorio correcto
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    cache_file = "catastro_cache.sqlite"
    
    print("="*50)
    print("🧹 LIMPIADOR DE CACHE DE CATASTRO")
    print("="*50)
    
    if os.path.exists(cache_file):
        try:
            print(f"🔍 Archivo de cache encontrado: {cache_file}")
            os.remove(cache_file)
            print(f"✅ Archivo de cache '{cache_file}' eliminado correctamente.")
            print("   La cache se regenerará en la próxima ejecución.")
            return True
        except Exception as e:
            print(f"❌ Error al eliminar el archivo de cache: {e}")
            print("   Por favor, intenta eliminar el archivo manualmente.")
            return False
    else:
        print(f"ℹ️  El archivo de cache '{cache_file}' no existe. No se necesita limpieza.")
        return True

if __name__ == "__main__":
    if limpiar_cache_catastro():
        print("\n🎉 Limpieza completada. Puedes ejecutar el programa principal de nuevo.")
    else:
        print("\n⚠️ La limpieza falló. Revisa los permisos del archivo o elimínalo manualmente.")