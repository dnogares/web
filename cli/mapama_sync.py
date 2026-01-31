#!/usr/bin/env python3
"""
CLI para gestión de sincronización MAPAMA
Herramienta de línea de comandos para administrar la sincronización de datos
"""

import click
import logging
import sys
import os
from pathlib import Path
import json
from typing import Optional, List, Tuple
from datetime import datetime

# Añadir directorio actual al path para importar módulos
sys.path.insert(0, str(Path(__file__).parent.parent))

from ogc_client import MAPAMAClient
from sync_mapama import MAPAMASyncer

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_db_url_from_config(config_path: str = "config_web.json") -> str:
    """Obtiene la URL de la base de datos desde variables de entorno o archivo de configuración."""
    # 1. Prioridad: Variables de entorno
    host = os.getenv("POSTGIS_HOST")
    if host:
        port = os.getenv("POSTGIS_PORT", "5432")
        dbname = os.getenv("POSTGIS_DATABASE", "GIS")
        user = os.getenv("POSTGIS_USER", "manuel")
        password = os.getenv("POSTGIS_PASSWORD", "Aa123456")
        return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

    # 2. Archivo de configuración
    try:
        full_path = Path(__file__).parent.parent / config_path
        if not full_path.exists():
            return "postgresql://user:pass@localhost/catastro_db"
            
        with open(full_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            db_cfg = cfg.get("database", {})
            if db_cfg:
                user = db_cfg.get("user", "postgres")
                password = db_cfg.get("password", "")
                host = db_cfg.get("host", "localhost")
                port = db_cfg.get("port", "5432")
                dbname = db_cfg.get("dbname", "catastro_db")
                return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
    except Exception as e:
        logger.error(f"Error cargando config: {e}")
    
    return "postgresql://user:pass@localhost/catastro_db"

# Obtener URL por defecto desde configuración
DEFAULT_DB_URL = get_db_url_from_config()

def parse_bbox(bbox_str: str) -> Optional[Tuple[float, float, float, float]]:
    """
    Parsea bbox desde string
    
    Args:
        bbox_str: Bbox como "minx,miny,maxx,maxy"
        
    Returns:
        Tupla con coordenadas o None
    """
    if not bbox_str:
        return None
    
    try:
        coords = [float(x.strip()) for x in bbox_str.split(',')]
        if len(coords) != 4:
            raise ValueError("Se requieren 4 coordenadas")
        return tuple(coords)
    except Exception as e:
        logger.error(f"Error parseando bbox: {e}")
        return None

@click.group()
@click.option('--db-url', default=DEFAULT_DB_URL, help='URL de conexión a PostgreSQL')
@click.option('--verbose', '-v', is_flag=True, help='Modo verbose')
@click.pass_context
def cli(ctx, db_url, verbose):
    """CLI para gestión de sincronización MAPAMA"""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    ctx.ensure_object(dict)
    ctx.obj['db_url'] = db_url

@cli.command()
@click.pass_context
def list(ctx):
    """Lista todas las colecciones disponibles en MAPAMA"""
    click.echo("🔍 Obteniendo colecciones disponibles...")
    
    try:
        client = MAPAMAClient()
        collections = client.get_collections()
        
        if not collections:
            click.echo("❌ No se encontraron colecciones")
            return
        
        # Agrupar por namespace
        namespaces = {}
        for coll in collections:
            namespace = coll.id.split(':')[0] if ':' in coll.id else 'root'
            if namespace not in namespaces:
                namespaces[namespace] = []
            namespaces[namespace].append(coll)
        
        # Mostrar por namespace
        for namespace, colls in sorted(namespaces.items()):
            click.echo(f"\n📂 {namespace.upper()}:")
            for coll in colls:
                click.echo(f"  • {coll.id}")
                if coll.title:
                    click.echo(f"    {coll.title}")
        
        click.echo(f"\n✅ Total: {len(collections)} colecciones en {len(namespaces)} namespaces")
        
    except Exception as e:
        click.echo(f"❌ Error: {e}")
        sys.exit(1)

@cli.command()
@click.argument('collection_id')
@click.pass_context
def info(ctx, collection_id):
    """Muestra información detallada de una colección"""
    click.echo(f"📊 Obteniendo información de {collection_id}...")
    
    try:
        client = MAPAMAClient()
        
        # Obtener metadatos
        metadata = client.get_collection_metadata(collection_id)
        
        click.echo(f"\n📋 {collection_id}")
        click.echo(f"Title: {metadata.get('title', 'N/A')}")
        click.echo(f"Description: {metadata.get('description', 'N/A')}")
        
        # Extent
        extent = metadata.get('extent', {})
        if extent and 'spatial' in extent:
            bbox = extent['spatial'].get('bbox', [])
            if bbox:
                click.echo(f"Extent: {bbox}")
        
        # CRS
        crs = metadata.get('crs', [])
        if crs:
            click.echo(f"CRS: {crs}")
        
        # Links
        links = metadata.get('links', [])
        if links:
            click.echo(f"\n🔗 Links ({len(links)}):")
            for link in links[:5]:  # Mostrar solo primeros 5
                click.echo(f"  • {link.get('rel', 'N/A')}: {link.get('href', 'N/A')}")
        
        # Propiedades consultables
        queryables = client.get_queryables(collection_id)
        if queryables:
            click.echo(f"\n🔍 Propiedades consultables ({len(queryables)}):")
            for prop_name, prop_type in list(queryables.items())[:10]:
                click.echo(f"  • {prop_name}: {prop_type.type}")
            if len(queryables) > 10:
                click.echo(f"  ... y {len(queryables) - 10} más")
        
        # Estadísticas
        stats = client.get_collection_stats(collection_id)
        if stats and 'error' not in stats:
            click.echo(f"\n📈 Estadísticas:")
            click.echo(f"  • CRS: {stats.get('crs', 'N/A')}")
            click.echo(f"  • Campos: {stats.get('total_fields', 0)}")
            click.echo(f"  • Tipos de geometría: {stats.get('geometry_types', {})}")
        
    except Exception as e:
        click.echo(f"❌ Error: {e}")
        sys.exit(1)

@cli.command()
@click.argument('collection_id')
@click.option('--bbox', help='Bounding box: minx,miny,maxx,maxy')
@click.option('--limit', type=int, default=None, help='Límite de features a descargar')
@click.option('--strategy', default='replace', 
              type=click.Choice(['replace', 'append', 'upsert']),
              help='Estrategia de actualización')
@click.pass_context
def sync(ctx, collection_id, bbox, limit, strategy):
    """Sincroniza una colección específica"""
    click.echo(f"🔄 Sincronizando {collection_id}...")
    
    try:
        syncer = MAPAMASyncer(ctx.obj['db_url'])
        
        # Probar conexión
        if not syncer.test_connection():
            click.echo("❌ Error de conexión a la base de datos")
            sys.exit(1)
        
        # Crear tabla de control si no existe
        syncer.create_sync_status_table()
        
        # Parsear bbox
        bbox_tuple = parse_bbox(bbox)
        
        # Sincronizar
        with click.progressbar(length=100, label='Progreso') as bar:
            def update_progress(current, total):
                if total > 0:
                    percentage = int((current / total) * 100)
                    bar.update(percentage - bar.pos)
            
            success = syncer.sync_collection(
                collection_id=collection_id,
                bbox=bbox_tuple,
                update_strategy=strategy,
                limit=limit
            )
        
        if success:
            click.echo(f"✅ Sincronización completada: {collection_id}")
            
            # Mostrar estado final
            status = syncer.get_sync_status(collection_id=collection_id)
            if status:
                s = status[0]
                click.echo(f"  • Features: {s['feature_count']}")
                click.echo(f"  • Estado: {s['status']}")
                click.echo(f"  • Última sincronización: {s['last_sync']}")
        else:
            click.echo(f"❌ Error en sincronización: {collection_id}")
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Error: {e}")
        sys.exit(1)

@cli.command()
@click.argument('namespace')
@click.option('--bbox', help='Bounding box: minx,miny,maxx,maxy')
@click.option('--limit', type=int, default=None, help='Límite por colección')
@click.pass_context
def sync_namespace(ctx, namespace, bbox, limit):
    """Sincroniza todas las colecciones de un namespace"""
    click.echo(f"🔄 Sincronizando namespace: {namespace}")
    
    try:
        syncer = MAPAMASyncer(ctx.obj['db_url'])
        
        # Probar conexión
        if not syncer.test_connection():
            click.echo("❌ Error de conexión a la base de datos")
            sys.exit(1)
        
        # Crear tabla de control si no existe
        syncer.create_sync_status_table()
        
        # Parsear bbox
        bbox_tuple = parse_bbox(bbox)
        
        # Sincronizar namespace
        results = syncer.sync_namespace(
            namespace=namespace,
            bbox=bbox_tuple,
            limit=limit
        )
        
        # Mostrar resultados
        successful = sum(results.values())
        total = len(results)
        
        click.echo(f"\n📊 Resultados del namespace {namespace}:")
        click.echo(f"  • Exitosas: {successful}/{total}")
        click.echo(f"  • Fallidas: {total - successful}/{total}")
        
        if results:
            click.echo(f"\n📋 Detalle:")
            for collection_id, success in results.items():
                status = "✅" if success else "❌"
                click.echo(f"  {status} {collection_id}")
        
    except Exception as e:
        click.echo(f"❌ Error: {e}")
        sys.exit(1)

@cli.command()
@click.option('--collection', help='Filtrar por colección específica')
@click.option('--namespace', help='Filtrar por namespace')
@click.option('--status', help='Filtrar por estado')
@click.pass_context
def status(ctx, collection, namespace, status):
    """Muestra estado de sincronización"""
    click.echo("📊 Estado de sincronización:")
    
    try:
        syncer = MAPAMASyncer(ctx.obj['db_url'])
        
        # Obtener estado
        records = syncer.get_sync_status(
            collection_id=collection,
            namespace=namespace
        )
        
        # Filtrar por estado si se especifica
        if status:
            records = [r for r in records if r.get('status') == status]
        
        if not records:
            click.echo("  No hay registros que coincidan con los filtros")
            return
        
        # Agrupar por namespace
        namespaces = {}
        for record in records:
            ns = record.get('namespace', 'root')
            if ns not in namespaces:
                namespaces[ns] = []
            namespaces[ns].append(record)
        
        # Mostrar por namespace
        total_synced = 0
        total_features = 0
        
        for ns, ns_records in sorted(namespaces.items()):
            click.echo(f"\n📂 {ns.upper()}:")
            
            for record in ns_records:
                status_icon = "✅" if record['status'] == 'synced' else "❌" if record['status'] == 'error' else "⏳"
                click.echo(f"  {status_icon} {record['collection_id']}")
                click.echo(f"    Features: {record['feature_count']:,}")
                click.echo(f"    Última sync: {record['last_sync']}")
                if record.get('error_message'):
                    click.echo(f"    Error: {record['error_message']}")
                
                if record['status'] == 'synced':
                    total_synced += 1
                    total_features += record['feature_count'] or 0
        
        # Resumen
        click.echo(f"\n📈 Resumen:")
        click.echo(f"  • Colecciones sincronizadas: {total_synced}/{len(records)}")
        click.echo(f"  • Total features: {total_features:,}")
        
    except Exception as e:
        click.echo(f"❌ Error: {e}")
        sys.exit(1)

@cli.command()
@click.pass_context
def reindex(ctx):
    """Recrea índices espaciales y optimiza tablas"""
    click.echo("🔄 Recreando índices...")
    
    try:
        syncer = MAPAMASyncer(ctx.obj['db_url'])
        
        # Obtener tablas sincronizadas
        records = syncer.get_sync_status()
        
        if not records:
            click.echo("❌ No hay tablas sincronizadas")
            return
        
        # Recrear índices para cada tabla
        with click.progressbar(records, label='Reindexando') as tables:
            for record in tables:
                table_name = record['table_name']
                try:
                    syncer.create_spatial_index(table_name)
                    syncer.optimize_table(table_name)
                    click.echo(f"✅ {table_name}")
                except Exception as e:
                    click.echo(f"❌ {table_name}: {e}")
        
        click.echo("✅ Reindexación completada")
        
    except Exception as e:
        click.echo(f"❌ Error: {e}")
        sys.exit(1)

@cli.command()
@click.argument('output_file', type=click.Path())
@click.pass_context
def export(ctx, output_file):
    """Exporta estado de sincronización a JSON"""
    click.echo(f"📤 Exportando estado a {output_file}...")
    
    try:
        syncer = MAPAMASyncer(ctx.obj['db_url'])
        
        # Obtener todo el estado
        records = syncer.get_sync_status()
        
        # Preparar datos para exportación
        export_data = {
            "export_date": datetime.now().isoformat(),
            "total_collections": len(records),
            "collections": records
        }
        
        # Escribir archivo
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, default=str, ensure_ascii=False)
        
        click.echo(f"✅ Exportado: {len(records)} colecciones")
        
    except Exception as e:
        click.echo(f"❌ Error: {e}")
        sys.exit(1)

@cli.command()
@click.argument('collection_id')
@click.option('--limit', type=int, default=100, help='Límite de features a descargar')
@click.option('--output', type=click.Path(), help='Archivo de salida GeoJSON')
@click.pass_context
def download(ctx, collection_id, limit, output):
    """Descarga una muestra de features de una colección"""
    click.echo(f"⬇️ Descargando muestra de {collection_id}...")
    
    try:
        client = MAPAMAClient()
        
        # Descargar features
        gdf = client.download_features(
            collection_id=collection_id,
            limit=limit,
            paginate=False
        )
        
        if gdf.empty:
            click.echo("❌ No hay features disponibles")
            return
        
        click.echo(f"✅ Descargados {len(gdf)} features")
        
        # Mostrar información
        click.echo(f"CRS: {gdf.crs}")
        click.echo(f"Columnas: {list(gdf.columns)}")
        
        # Guardar si se especificó archivo
        if output:
            if output.endswith('.geojson'):
                gdf.to_file(output, driver='GeoJSON')
            elif output.endswith('.gpkg'):
                gdf.to_file(output, driver='GPKG')
            else:
                gdf.to_file(output, driver='GeoJSON')
            click.echo(f"💾 Guardado en: {output}")
        
    except Exception as e:
        click.echo(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    cli()
