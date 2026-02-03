#!/usr/bin/env python3
"""
Script de verificación automática para servidor_final.py
Ejecuta el servidor corregido y verifica sus endpoints.
"""
import subprocess
import sys
import time
import os
import requests
import socket

# Configuración
SERVER_FILE = "servidor_final.py"
PORT = 8000
BASE_URL = f"http://localhost:{PORT}"

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def main():
    print(f"🔍 Verificando {SERVER_FILE}...")
    
    # 1. Verificar existencia del archivo
    if not os.path.exists(SERVER_FILE):
        print(f"❌ Error: No se encuentra {SERVER_FILE}")
        return

    server_process = None
    started_by_script = False

    # 2. Gestionar el proceso del servidor
    if is_port_in_use(PORT):
        print(f"⚠️ El puerto {PORT} ya está en uso. Asumiendo que el servidor ya está corriendo.")
    else:
        print(f"🚀 Iniciando servidor en puerto {PORT}...")
        server_process = subprocess.Popen(
            [sys.executable, SERVER_FILE],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=os.path.dirname(os.path.abspath(__file__))
        )
        started_by_script = True
        
        # Esperar arranque
        print("⏳ Esperando arranque del servidor...")
        time.sleep(2)

    try:
        # 3. Verificar conectividad básica
        try:
            resp = requests.get(BASE_URL, timeout=2)
            print(f"✅ Servidor online (Status: {resp.status_code})")
        except requests.ConnectionError:
            print("❌ No se pudo conectar al servidor.")
            if started_by_script and server_process:
                out, err = server_process.communicate(timeout=1)
                print(f"--- Salida del servidor ---\n{out}\n{err}")
            return

        # 4. Probar Endpoints Clave
        endpoints = [
            ("GET", "/", 200, "Visor HTML"),
            ("GET", "/api/v1/logs", 200, "Logs del sistema"),
            ("GET", "/api/v1/capas-disponibles", 200, "Catálogo de capas"),
            ("GET", "/api/v1/buscar-municipio?q=madrid", 200, "Búsqueda municipios"),
        ]

        print("\n🧪 Ejecutando pruebas de endpoints...")
        for method, path, expected_status, desc in endpoints:
            url = f"{BASE_URL}{path}"
            try:
                r = requests.get(url)
                if r.status_code == expected_status:
                    print(f"✅ {desc}: OK ({path})")
                else:
                    print(f"❌ {desc}: Falló - Status {r.status_code} (Esperado: {expected_status})")
            except Exception as e:
                print(f"❌ {desc}: Error de conexión - {e}")

        # 5. Prueba de POST (Simulación)
        print("\n🧪 Probando endpoint POST (Análisis)...")
        try:
            payload = {"referencia": "00000000000000"} # Referencia dummy
            r = requests.post(f"{BASE_URL}/api/v1/analizar-referencia", json=payload)
            if r.status_code == 200:
                data = r.json()
                print(f"✅ Análisis Referencia: OK (Respuesta: {data.get('status')})")
            else:
                print(f"❌ Análisis Referencia: Falló (Status: {r.status_code})")
        except Exception as e:
            print(f"❌ Análisis Referencia: Error - {e}")

    finally:
        # 6. Limpieza
        if started_by_script and server_process:
            print("\n🛑 Deteniendo servidor...")
            server_process.terminate()
            server_process.wait()
            print("✅ Servidor detenido correctamente")

if __name__ == "__main__":
    main()
