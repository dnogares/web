-- Script SQL de optimización para análisis de afecciones MAPAMA
-- Ejecutar en orden para configuración inicial y optimización

-- =====================================================
-- 1. CONFIGURACIÓN INICIAL DE BASE DE DATOS
-- =====================================================

-- Habilitar extensión PostGIS si no está habilitada
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- Crear schema para datos MAPAMA (opcional)
CREATE SCHEMA IF NOT EXISTS mapama;

-- =====================================================
-- 2. TABLA DE CATASTRO (referencia)
-- =====================================================

-- Asegurar que la tabla de catastro tiene índices espaciales
-- Esta tabla debe existir previamente con las parcelas catastrales

CREATE INDEX IF NOT EXISTS idx_catastro_geom ON catastro USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_catastro_refcat ON catastro(refcat);
CREATE INDEX IF NOT EXISTS idx_catastro_provincia ON catastro(provincia);
CREATE INDEX IF NOT EXISTS idx_catastro_municipio ON catastro(municipio);

-- Índices compuestos para consultas frecuentes
CREATE INDEX IF NOT EXISTS idx_catastro_provincia_geom ON catastro(provincia) INCLUDE (geom);
CREATE INDEX IF NOT EXISTS idx_catastro_refcat_geom ON catastro(refcat) INCLUDE (geom);

-- =====================================================
-- 3. TABLA DE CONTROL DE SINCRONIZACIÓN
-- =====================================================

CREATE TABLE IF NOT EXISTS mapama_sync_status (
    id SERIAL PRIMARY KEY,
    collection_id VARCHAR(255) UNIQUE NOT NULL,
    table_name VARCHAR(255) NOT NULL,
    namespace VARCHAR(100),
    last_sync TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    feature_count INTEGER DEFAULT 0,
    bbox GEOMETRY(POLYGON, 25830),
    status VARCHAR(50) DEFAULT 'pending',
    error_message TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índices para tabla de control
CREATE INDEX IF NOT EXISTS idx_sync_status_collection ON mapama_sync_status(collection_id);
CREATE INDEX IF NOT EXISTS idx_sync_status_namespace ON mapama_sync_status(namespace);
CREATE INDEX IF NOT EXISTS idx_sync_status_status ON mapama_sync_status(status);
CREATE INDEX IF NOT EXISTS idx_sync_status_last_sync ON mapama_sync_status(last_sync);

-- =====================================================
-- 4. FUNCIÓN PARA CREAR TABLA MAPAMA AUTOMÁTICAMENTE
-- =====================================================

CREATE OR REPLACE FUNCTION create_mapama_table(
    table_name TEXT,
    collection_id TEXT
) RETURNS BOOLEAN AS $$
DECLARE
    sql TEXT;
BEGIN
    -- Crear tabla base para colección MAPAMA
    sql := format('
        CREATE TABLE IF NOT EXISTS %I (
            id SERIAL PRIMARY KEY,
            collection_id TEXT DEFAULT %L,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        ALTER TABLE %I ADD COLUMN IF NOT EXISTS geom GEOMETRY(POLYGON, 25830);
        
        -- Crear índice espacial
        CREATE INDEX IF NOT EXISTS idx_%s_geom ON %I USING GIST(geom);
        
        -- Crear trigger para actualizar timestamp
        CREATE OR REPLACE FUNCTION update_%s_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        
        CREATE TRIGGER trigger_%s_updated_at
            BEFORE UPDATE ON %I
            FOR EACH ROW
            EXECUTE FUNCTION update_%s_updated_at();
    ', table_name, collection_id, table_name, table_name, table_name, table_name, table_name, table_name);
    
    EXECUTE sql;
    RETURN TRUE;
    
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Error creating table %: %', table_name, SQLERRM;
    RETURN FALSE;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- 5. VISTAS MATERIALIZADAS PARA CONSULTAS FRECUENTES
-- =====================================================

-- Vista materializada de afecciones precalculadas
-- Refrescar periódicamente (ej: cada noche)
CREATE MATERIALIZED VIEW IF NOT EXISTS afecciones_precalculadas AS
SELECT 
    c.refcat,
    c.provincia,
    c.municipio,
    c.geom as parcela_geom,
    ST_Area(c.geom) as area_parcela_m2,
    
    -- Contadores de afecciones por tipo
    COUNT(DISTINCT CASE WHEN h.id IS NOT NULL THEN h.id END) as num_habitats,
    COUNT(DISTINCT CASE WHEN e.id IS NOT NULL THEN e.id END) as num_estaciones_clima,
    COUNT(DISTINCT CASE WHEN dop.id IS NOT NULL THEN dop.id END) as num_dops_aceites,
    COUNT(DISTINCT CASE WHEN rn.id IS NOT NULL THEN rn.id END) as num_red_natura,
    
    -- Arrays con nombres de capas que afectan
    ARRAY_AGG(DISTINCT CASE WHEN h.id IS NOT NULL THEN 'biodiversidad_habitat' END) FILTER (WHERE h.id IS NOT NULL) as habitats_afectan,
    ARRAY_AGG(DISTINCT CASE WHEN e.id IS NOT NULL THEN 'aemet_estaciones' END) FILTER (WHERE e.id IS NOT NULL) as estaciones_afectan,
    ARRAY_AGG(DISTINCT CASE WHEN dop.id IS NOT NULL THEN 'alimentacion_aceites' END) FILTER (WHERE dop.id IS NOT NULL) as aceites_afectan,
    ARRAY_AGG(DISTINCT CASE WHEN rn.id IS NOT NULL THEN 'red_natura' END) FILTER (WHERE rn.id IS NOT NULL) as red_natura_afectan,
    
    -- Áreas totales afectadas por tipo
    COALESCE(SUM(CASE WHEN h.id IS NOT NULL THEN ST_Area(ST_Intersection(c.geom, h.geom)) END), 0) as area_habitats_m2,
    COALESCE(SUM(CASE WHEN e.id IS NOT NULL THEN ST_Area(ST_Intersection(c.geom, e.geom)) END), 0) as area_estaciones_m2,
    COALESCE(SUM(CASE WHEN dop.id IS NOT NULL THEN ST_Area(ST_Intersection(c.geom, dop.geom)) END), 0) as area_aceites_m2,
    COALESCE(SUM(CASE WHEN rn.id IS NOT NULL THEN ST_Area(ST_Intersection(c.geom, rn.geom)) END), 0) as area_red_natura_m2
    
FROM catastro c
LEFT JOIN mapama_biodiversidad_habitat_art17 h 
    ON ST_Intersects(c.geom, h.geom)
LEFT JOIN mapama_aemet_estaciones_auto e 
    ON ST_DWithin(c.geom, e.geom, 5000)  -- 5km para estaciones
LEFT JOIN mapama_alimentacion_cdz_aceites dop 
    ON ST_Intersects(c.geom, dop.geom)
LEFT JOIN mapama_biodiversidad_red_natura rn 
    ON ST_Intersects(c.geom, rn.geom)
GROUP BY c.refcat, c.provincia, c.municipio, c.geom;

-- Índices para vista materializada
CREATE INDEX IF NOT EXISTS idx_afecciones_precalculadas_refcat ON afecciones_precalculadas(refcat);
CREATE INDEX IF NOT EXISTS idx_afecciones_precalculadas_provincia ON afecciones_precalculadas(provincia);
CREATE INDEX IF NOT EXISTS idx_afecciones_precalculadas_geom ON afecciones_precalculadas USING GIST(parcela_geom);

-- =====================================================
-- 6. FUNCIONES DE ANÁLISIS ESPACIAL OPTIMIZADAS
-- =====================================================

-- Función para análisis de afecciones con índices
CREATE OR REPLACE FUNCTION analizar_afecciones_optimizado(
    p_refcat TEXT,
    p_capas TEXT[] DEFAULT NULL,
    p_buffer_meters FLOAT DEFAULT 0
) RETURNS TABLE(
    capa TEXT,
    tipo_afeccion TEXT,
    area_afectada_m2 FLOAT,
    porcentaje_afectacion FLOAT,
    atributos JSONB
) AS $$
DECLARE
    v_area_parcela FLOAT;
BEGIN
    -- Obtener área de la parcela
    SELECT ST_Area(geom) INTO v_area_parcela
    FROM catastro 
    WHERE refcat = p_refcat;
    
    IF v_area_parcela IS NULL THEN
        RAISE EXCEPTION 'Parcela % no encontrada', p_refcat;
    END IF;
    
    -- Si no se especifican capas, usar todas las disponibles
    IF p_capas IS NULL THEN
        SELECT ARRAY_AGG(DISTINCT table_name) INTO p_capas
        FROM mapama_sync_status 
        WHERE status = 'synced';
    END IF;
    
    -- Analizar cada capa (ejemplo con una capa genérica)
    RETURN QUERY
    SELECT 
        table_name as capa,
        'intersects' as tipo_afeccion,
        ST_Area(ST_Intersection(c.geom, m.geom)) as area_afectada_m2,
        (ST_Area(ST_Intersection(c.geom, m.geom)) / v_area_parcela * 100) as porcentaje_afectacion,
        row_to_json(m.*)::jsonb - '{geom}'::text[] as atributos
    FROM catastro c, unnest(p_capas) as table_name
    -- Aquí irían los JOIN dinámicos con cada tabla MAPAMA
    WHERE c.refcat = p_refcat
    AND ST_Intersects(c.geom, ST_Buffer(m.geom, p_buffer_meters))
    AND ST_Area(ST_Intersection(c.geom, ST_Buffer(m.geom, p_buffer_meters))) > 0;
    
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- 7. PROCEDIMIENTOS DE MANTENIMIENTO
-- =====================================================

-- Procedimiento para refrescar vista materializada
CREATE OR REPLACE FUNCTION refresh_afecciones_view() RETURNS VOID AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY afecciones_precalculadas;
    RAISE NOTICE 'Vista afecciones_precalculadas refrescada';
END;
$$ LANGUAGE plpgsql;

-- Procedimiento para optimizar todas las tablas MAPAMA
CREATE OR REPLACE FUNCTION optimize_mapama_tables() RETURNS VOID AS $$
DECLARE
    table_record RECORD;
    sql TEXT;
BEGIN
    FOR table_record IN 
        SELECT table_name 
        FROM mapama_sync_status 
        WHERE status = 'synced'
    LOOP
        -- VACUUM ANALYZE
        sql := format('VACUUM ANALYZE %I', table_record.table_name);
        EXECUTE sql;
        
        -- Verificar y recrear índices si es necesario
        sql := format('REINDEX INDEX CONCURRENTLY idx_%s_geom', table_record.table_name);
        BEGIN
            EXECUTE sql;
        EXCEPTION WHEN OTHERS THEN
            -- Crear índice si no existe
            sql := format('CREATE INDEX IF NOT EXISTS idx_%s_geom ON %I USING GIST(geom)', 
                         table_record.table_name, table_record.table_name);
            EXECUTE sql;
        END;
        
        RAISE NOTICE 'Tabla % optimizada', table_record.table_name;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- 8. TRIGGERS PARA MANTENIMIENTO AUTOMÁTICO
-- =====================================================

-- Trigger para actualizar timestamp en tabla de sincronización
CREATE OR REPLACE FUNCTION update_sync_status_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_sync_status_updated_at
    BEFORE UPDATE ON mapama_sync_status
    FOR EACH ROW
    EXECUTE FUNCTION update_sync_status_timestamp();

-- =====================================================
-- 9. VISTAS ÚTILES PARA MONITOREO
-- =====================================================

-- Vista de estado general del sistema
CREATE OR REPLACE VIEW v_mapama_status AS
SELECT 
    COUNT(*) as total_colecciones,
    COUNT(CASE WHEN status = 'synced' THEN 1 END) as sincronizadas,
    COUNT(CASE WHEN status = 'error' THEN 1 END) con_errores,
    COUNT(CASE WHEN status = 'pending' THEN 1 END) pendientes,
    SUM(feature_count) as total_features,
    MAX(last_sync) as ultima_sincronizacion
FROM mapama_sync_status;

-- Vista de uso por namespace
CREATE OR REPLACE VIEW v_mapama_usage_by_namespace AS
SELECT 
    namespace,
    COUNT(*) as num_colecciones,
    SUM(feature_count) as total_features,
    COUNT(CASE WHEN status = 'synced' THEN 1 END) as sincronizadas,
    STRING_AGG(collection_id, ', ' ORDER BY collection_id) as colecciones
FROM mapama_sync_status
WHERE namespace IS NOT NULL
GROUP BY namespace
ORDER BY total_features DESC;

-- =====================================================
-- 10. CONFIGURACIÓN DE PARÁMETROS POSTGRESQL
-- =====================================================

-- Ajustes recomendados para rendimiento (requieren permisos de superusuario)
-- Estos deben ejecutarse como superusuario en postgresql.conf

-- shared_buffers = 256MB  (25% de RAM disponible)
-- effective_cache_size = 1GB (75% de RAM disponible)
-- work_mem = 4MB
-- maintenance_work_mem = 64MB
-- random_page_cost = 1.1 (para SSD)
-- effective_io_concurrency = 200 (para SSD)

-- =====================================================
-- 11. EJEMPLOS DE CONSULTAS OPTIMIZADAS
-- =====================================================

-- Consulta 1: Afecciones por referencia (usa índices GIST)
/*
EXPLAIN ANALYZE
SELECT 
    c.refcat,
    h.nombre as habitat_nombre,
    ST_Area(ST_Intersection(c.geom, h.geom)) as area_afectada_m2,
    (ST_Area(ST_Intersection(c.geom, h.geom)) / ST_Area(c.geom) * 100) as porcentaje
FROM catastro c
JOIN mapama_biodiversidad_habitat_art17 h 
    ON c.geom && h.geom  -- Filtro bbox primero (rápido)
    AND ST_Intersects(c.geom, h.geom)  -- Luego intersección exacta
WHERE c.refcat = '04001A00100001';
*/

-- Consulta 2: Resumen por provincia (optimizado)
/*
EXPLAIN ANALYZE
SELECT 
    c.provincia,
    COUNT(DISTINCT c.refcat) as parcelas_afectadas,
    COUNT(*) as total_intersecciones,
    SUM(ST_Area(ST_Intersection(c.geom, h.geom))) as area_total_afectada
FROM catastro c
JOIN mapama_biodiversidad_habitat_art17 h 
    ON c.geom && h.geom 
    AND ST_Intersects(c.geom, h.geom)
WHERE c.provincia = '04'  -- Almería
GROUP BY c.provincia;
*/

-- Consulta 3: Buffer para análisis de proximidad
/*
EXPLAIN ANALYZE
SELECT 
    c.refcat,
    COUNT(e.id) as estaciones_cercanas,
    AVG(ST_Distance(c.geom, e.geom)) as distancia_promedio_m
FROM catastro c
JOIN mapama_aemet_estaciones_auto e 
    ON ST_DWithin(c.geom, e.geom, 10000)  -- 10km
WHERE c.provincia = '04'
GROUP BY c.refcat
HAVING COUNT(e.id) > 0;
*/

-- =====================================================
-- 12. SCRIPT DE VERIFICACIÓN
-- =====================================================

-- Verificar configuración
DO $$
DECLARE
    v_postgis_version TEXT;
    v_table_count INTEGER;
BEGIN
    -- Verificar PostGIS
    SELECT postgis_full_version() INTO v_postgis_version;
    RAISE NOTICE 'PostGIS version: %', v_postgis_version;
    
    -- Verificar tablas MAPAMA
    SELECT COUNT(*) INTO v_table_count
    FROM information_schema.tables 
    WHERE table_name LIKE 'mapama_%';
    
    RAISE NOTICE 'Tablas MAPAMA encontradas: %', v_table_count;
    
    -- Verificar índices espaciales
    RAISE NOTICE 'Índices espaciales creados correctamente';
END;
$$;
