#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para automatizar la reorganización del proyecto web6
VERSION AUTOMATICA - SIN CONFIRMACION
"""

import os
import shutil
import json
from pathlib import Path
from datetime import datetime

def print_header(text):
    print(f"\n{'='*60}")
    print(f"{text}")
    print(f"{'='*60}\n")

def print_success(text):
    print(f"[OK] {text}")

def print_warning(text):
    print(f"[WARN] {text}")

def print_error(text):
    print(f"[ERROR] {text}")

def print_info(text):
    print(f"[INFO] {text}")

def create_folder(path):
    Path(path).mkdir(parents=True, exist_ok=True)
    return True

def move_file(src, dst, create_dst=True):
    try:
        src_path = Path(src)
        dst_path = Path(dst)
        
        if not src_path.exists():
            return False
        
        if create_dst:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
        
        shutil.move(str(src_path), str(dst_path))
        print_success(f"Movido: {src} -> {dst}")
        return True
    except Exception as e:
        print_error(f"Error moviendo {src}: {e}")
        return False

def delete_file(path):
    try:
        p = Path(path)
        if p.exists():
            p.unlink()
            print_success(f"Eliminado: {path}")
            return True
    except Exception as e:
        print_error(f"Error eliminando {path}: {e}")
    return False

def backup_project(root_dir):
    print_header("CREANDO BACKUP")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"web6_backup_{timestamp}"
    backup_path = Path(root_dir).parent / backup_name
    
    try:
        print_info(f"Creando backup en: {backup_path}")
        shutil.copytree(root_dir, backup_path)
        print_success(f"Backup completado")
        return True
    except Exception as e:
        print_error(f"Error creando backup: {e}")
        return False

def create_structure(root_dir):
    print_header("CREANDO ESTRUCTURA DE CARPETAS")
    
    folders = [
        "src/core",
        "src/api/routes",
        "src/backend/database",
        "src/backend/services",
        "src/utils",
        "src/cli",
        "src/config",
        "data/capas",
        "data/geodata",
        "data/cache",
        "tests",
        "scripts",
        "docs",
    ]
    
    for folder in folders:
        folder_path = Path(root_dir) / folder
        if create_folder(folder_path):
            print_success(f"Carpeta: {folder}")

def move_core_files(root_dir):
    print_header("MOVIENDO ARCHIVOS CORE")
    
    files = [
        ("catastro.py", "src/core/catastro_engine.py"),
        ("ogc_client.py", "src/core/ogc_client.py"),
        ("gis_db.py", "src/backend/services/gis_service.py"),
    ]
    
    for src, dst in files:
        src_path = Path(root_dir) / src
        dst_path = Path(root_dir) / dst
        if src_path.exists():
            move_file(src_path, dst_path)

def move_services_files(root_dir):
    print_header("MOVIENDO ARCHIVOS DE SERVICIOS")
    
    files = [
        ("urbanismo.py", "src/backend/services/urbanismo_service.py"),
        ("afecciones.py", "src/backend/services/afecciones_service.py"),
    ]
    
    for src, dst in files:
        src_path = Path(root_dir) / src
        dst_path = Path(root_dir) / dst
        if src_path.exists():
            move_file(src_path, dst_path)

def move_cli_files(root_dir):
    print_header("MOVIENDO ARCHIVOS CLI")
    
    files = [
        ("sync_mapama.py", "src/cli/mapama_sync.py"),
    ]
    
    for src, dst in files:
        src_path = Path(root_dir) / src
        dst_path = Path(root_dir) / dst
        if src_path.exists():
            move_file(src_path, dst_path)

def move_scripts(root_dir):
    print_header("MOVIENDO SCRIPTS")
    
    scripts = [
        "check_gis.py",
        "check_gis_perf.py",
        "limpiar_cache.py",
        "iniciar_nuevo_visor.py",
        "convert_to_fgb.py",
        "descargar_capa.py",
        "limpiar_archivos.py",
        "list_layers_util.py",
        "repro_coords.py",
        "verificarservidor.py",
        "servidor_botones.py",
        "servidor_final.py",
    ]
    
    for script in scripts:
        src_path = Path(root_dir) / script
        dst_path = Path(root_dir) / "scripts" / script
        if src_path.exists():
            move_file(src_path, dst_path)

def move_tests(root_dir):
    print_header("MOVIENDO TESTS")
    
    test_files = []
    root_path = Path(root_dir)
    
    for f in root_path.glob("test_*.py"):
        test_files.append(f.name)
    
    for f in root_path.glob("debug_*.py"):
        test_files.append(f.name)
    
    for test_file in test_files:
        src_path = Path(root_dir) / test_file
        dst_path = Path(root_dir) / "tests" / test_file
        if src_path.exists():
            move_file(src_path, dst_path)

def move_config_files(root_dir):
    print_header("MOVIENDO CONFIGURACION")
    
    config_files = [
        ("config.json", "src/config/config.json"),
        ("config_web.json", "src/config/config_web.json"),
    ]
    
    for src, dst in config_files:
        src_path = Path(root_dir) / src
        dst_path = Path(root_dir) / dst
        if src_path.exists():
            move_file(src_path, dst_path)

def move_data_files(root_dir):
    print_header("MOVIENDO DATOS")
    
    data_files = [
        ("mapa_municipios.json", "data/geodata/mapa_municipios.json"),
        ("datosdeGIS.csv", "data/datosdeGIS.csv"),
    ]
    
    for src, dst in data_files:
        src_path = Path(root_dir) / src
        dst_path = Path(root_dir) / dst
        if src_path.exists():
            move_file(src_path, dst_path)

def delete_log_files(root_dir):
    print_header("ELIMINANDO LOGS")
    
    count = 0
    root_path = Path(root_dir)
    
    for f in root_path.glob("*.txt"):
        if f.name not in ["check_fgb.txt", "estructura.txt"]:
            delete_file(f)
            count += 1
    
    print_info(f"Archivos de log eliminados: {count}")

def delete_duplicates(root_dir):
    print_header("ELIMINANDO DUPLICADOS")
    
    files_to_delete = [
        "catastro4.py",
        "visor_functions_complete.py",
        "visor_functions_integrated.py",
    ]
    
    for f in files_to_delete:
        delete_file(Path(root_dir) / f)

def create_init_files(root_dir):
    print_header("CREANDO ARCHIVOS __init__.py")
    
    init_files = [
        "src/__init__.py",
        "src/core/__init__.py",
        "src/api/__init__.py",
        "src/api/routes/__init__.py",
        "src/backend/__init__.py",
        "src/backend/database/__init__.py",
        "src/backend/services/__init__.py",
        "src/utils/__init__.py",
        "src/cli/__init__.py",
        "src/config/__init__.py",
        "tests/__init__.py",
        "scripts/__init__.py",
    ]
    
    for init_file in init_files:
        path = Path(root_dir) / init_file
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.touch()
            print_success(f"Creado: {init_file}")

def main():
    root_dir = Path.cwd()
    
    print_header("REORGANIZADOR DE PROYECTO WEB6")
    print_info(f"Directorio raiz: {root_dir}")
    print_info("Iniciando reorganizacion...")
    
    if not backup_project(root_dir):
        print_error("No se pudo crear backup. Abortando.")
        return
    
    create_structure(root_dir)
    create_init_files(root_dir)
    move_core_files(root_dir)
    move_services_files(root_dir)
    move_cli_files(root_dir)
    move_scripts(root_dir)
    move_tests(root_dir)
    move_config_files(root_dir)
    move_data_files(root_dir)
    delete_duplicates(root_dir)
    delete_log_files(root_dir)
    
    print_header("REORGANIZACION COMPLETADA")
    print_success("Estructura del proyecto reorganizada exitosamente")
    print_info("Proximos pasos:")
    print("  1. Revisar imports en main.py")
    print("  2. Ejecutar: python -m pytest tests/")
    print("  3. Ejecutar: python main.py")
    print("  4. Hacer commit: git add . && git commit -m 'refactor: restructure project'")
    
if __name__ == "__main__":
    main()
