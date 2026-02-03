#!/usr/bin/env python3
"""Script para probar sintaxis de main.py"""

import ast

def check_syntax(filename):
    """Verificar sintaxis de un archivo Python"""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Intentar parsear el AST
        ast.parse(content)
        print(f"✅ Sintaxis correcta en {filename}")
        return True
        
    except SyntaxError as e:
        print(f"❌ Error de sintaxis en {filename}:")
        print(f"   Línea {e.lineno}: {e.text}")
        print(f"   {e.msg}")
        return False
    except Exception as e:
        print(f"❌ Error leyendo {filename}: {e}")
        return False

if __name__ == "__main__":
    print("🔍 Verificando sintaxis de main.py...")
    check_syntax("main.py")
