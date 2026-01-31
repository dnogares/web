import requests
import json

def test_api():
    url = "http://localhost:8000/api/v1/analizar-afecciones"
    # Usar una referencia válida que sepa que existe o una de prueba
    payload = {"referencia": "1234567AB1234C"} 
    
    print(f"Probando conexión a: {url}")
    try:
        resp = requests.post(url, json=payload)
        if resp.status_code == 200:
            data = resp.json()
            print("Respuesta recibida:")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            
            # Verificar si es la respuesta simulada antigua
            if "afecciones" in data.get("data", {}):
                afs = data["data"]["afecciones"]
                if len(afs) > 0 and afs[0].get("tipo") == "Dominio Público":
                    print("\n⚠️ ALERTA: El servidor está devolviendo datos SIMULADOS ANTIGUOS.")
                    print("SOLUCIÓN: Reinicia el servidor (main.py) para aplicar los cambios.")
                else:
                    print("\n✅ El servidor parece estar ejecutando la LÓGICA NUEVA.")
        else:
            print(f"Error {resp.status_code}: {resp.text}")
            
    except Exception as e:
        print(f"No se pudo conectar: {e}")

if __name__ == "__main__":
    test_api()
