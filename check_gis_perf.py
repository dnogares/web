from sqlalchemy import text
from gis_db import GISDatabase

def check_perf():
    db = GISDatabase()
    if not db.test_connection():
        print("Error: No se pudo conectar a la DB")
        return

    # Comprobar si existen índices GIST en las tablas del esquema afecciones
    sql = """
    SELECT
        t.relname as table_name,
        i.relname as index_name,
        a.attname as column_name
    FROM
        pg_class t,
        pg_class i,
        pg_index ix,
        pg_attribute a,
        pg_namespace n
    WHERE
        t.oid = ix.indrelid
        AND i.oid = ix.indexrelid
        AND a.attrelid = t.oid
        AND a.attnum = ANY(ix.indkey)
        AND t.relnamespace = n.oid
        AND n.nspname = 'afecciones'
        AND i.relname LIKE '%gist%'
    ORDER BY
        t.relname;
    """
    
    with db.engine.connect() as conn:
        result = conn.execute(text(sql))
        indexes = result.fetchall()
        
        print(f"Indices espaciales encontrados: {len(indexes)}")
        for idx in indexes:
            print(f"- Tabla: {idx[0]}, Índice: {idx[1]}, Columna: {idx[2]}")

if __name__ == "__main__":
    check_perf()
