-- ============================================================
-- ESQUEMA POSTGRESQL + POSTGIS
-- Sistema de Análisis Catastral
-- ============================================================

-- Crear extensión PostGIS si no existe
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- ============================================================
-- 1. TABLA: parcelas_catastro
--    Almacena geometrías de parcelas consultadas
-- ============================================================

CREATE TABLE IF NOT EXISTS parcelas_catastro (
    id SERIAL PRIMARY KEY,
    referencia_catastral VARCHAR(20) UNIQUE NOT NULL,
    
    -- Geometría (EPSG:25830 o 4326 según configuración)
    geom GEOMETRY(Polygon, 25830),
    
    -- Metadatos catastrales
    provincia VARCHAR(100),
    municipio VARCHAR(100),
    via_nombre TEXT,
    numero_via VARCHAR(20),
    
    -- Métricas
    area_catastral NUMERIC(12, 2),  -- m²
    perimetro NUMERIC(12, 2),       -- m
    
    -- Datos adicionales de catastro
    uso_principal VARCHAR(100),
    clase_suelo VARCHAR(50),
    
    -- Control de datos
    fecha_consulta TIMESTAMP DEFAULT NOW(),
    fecha_actualizacion TIMESTAMP,
    origen_datos VARCHAR(50) DEFAULT 'catastro_gml',
    
    -- JSON con datos completos de catastro
    datos_json JSONB,
    
    CONSTRAINT chk_refcat CHECK (length(referencia_catastral) >= 14)
);

-- Índices espaciales (CRÍTICO para rendimiento)
CREATE INDEX idx_parcelas_geom ON parcelas_catastro USING GIST(geom);
CREATE INDEX idx_parcelas_refcat ON parcelas_catastro(referencia_catastral);
CREATE INDEX idx_parcelas_municipio ON parcelas_catastro(municipio);
CREATE INDEX idx_parcelas_fecha ON parcelas_catastro(fecha_consulta);

-- ============================================================
-- 2. TABLA: edificios_catastro
--    Almacena geometrías de edificios
-- ============================================================

CREATE TABLE IF NOT EXISTS edificios_catastro (
    id SERIAL PRIMARY KEY,
    referencia_catastral VARCHAR(20) NOT NULL,
    
    -- Geometría
    geom GEOMETRY(Polygon, 25830),
    
    -- Datos del edificio
    numero_plantas INTEGER,
    uso_edificio VARCHAR(100),
    area_construida NUMERIC(12, 2),
    
    -- Relación con parcela
    parcela_id INTEGER REFERENCES parcelas_catastro(id) ON DELETE CASCADE,
    
    -- Control
    fecha_registro TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_edificios_geom ON edificios_catastro USING GIST(geom);
CREATE INDEX idx_edificios_refcat ON edificios_catastro(referencia_catastral);
CREATE INDEX idx_edificios_parcela ON edificios_catastro(parcela_id);

-- ============================================================
-- 3. TABLA: analisis_urbanistico
--    Cache de análisis urbanísticos
-- ============================================================

CREATE TABLE IF NOT EXISTS analisis_urbanistico (
    id SERIAL PRIMARY KEY,
    parcela_id INTEGER REFERENCES parcelas_catastro(id) ON DELETE CASCADE,
    
    -- Clasificación urbanística
    clasificacion_suelo VARCHAR(100),
    calificacion_suelo VARCHAR(100),
    zona_urbanistica VARCHAR(100),
    
    -- Parámetros urbanísticos
    edificabilidad NUMERIC(6, 3),           -- m²/m²
    ocupacion_maxima NUMERIC(5, 2),        -- %
    retranqueos_json JSONB,                -- Distancias a linderos
    altura_maxima NUMERIC(6, 2),           -- metros
    numero_plantas_max INTEGER,
    
    -- Superficie máxima edificable
    superficie_edificable NUMERIC(12, 2),  -- m²
    
    -- Usos permitidos (array de texto)
    usos_permitidos TEXT[],
    usos_prohibidos TEXT[],
    
    -- Afecciones detectadas
    afecciones_detectadas BOOLEAN DEFAULT FALSE,
    detalle_afecciones JSONB,
    
    -- Archivos generados
    pdf_informe_path TEXT,
    
    -- Control
    fecha_analisis TIMESTAMP DEFAULT NOW(),
    analista VARCHAR(100),
    
    CONSTRAINT chk_edificabilidad CHECK (edificabilidad >= 0 AND edificabilidad <= 10),
    CONSTRAINT chk_ocupacion CHECK (ocupacion_maxima >= 0 AND ocupacion_maxima <= 100)
);

CREATE INDEX idx_analisis_parcela ON analisis_urbanistico(parcela_id);
CREATE INDEX idx_analisis_fecha ON analisis_urbanistico(fecha_analisis);

-- ============================================================
-- 4. TABLA: intersecciones_afecciones
--    Registro de intersecciones calculadas
-- ============================================================

CREATE TABLE IF NOT EXISTS intersecciones_afecciones (
    id SERIAL PRIMARY KEY,
    parcela_id INTEGER REFERENCES parcelas_catastro(id) ON DELETE CASCADE,
    
    -- Identificación de la capa de afección
    capa_nombre VARCHAR(100) NOT NULL,
    capa_tipo VARCHAR(50),  -- proteccion, infraestructura, riesgo, etc.
    
    -- Clasificación dentro de la capa
    clasificacion VARCHAR(100),
    
    -- Geometría de la intersección
    geom_interseccion GEOMETRY(Polygon, 25830),
    
    -- Métricas
    area_interseccion NUMERIC(12, 2),      -- m²
    porcentaje_afectacion NUMERIC(5, 2),  -- %
    
    -- Información adicional de la afección
    info_adicional JSONB,
    
    -- Normativa aplicable
    normativa TEXT,
    restricciones TEXT,
    
    -- Control
    fecha_calculo TIMESTAMP DEFAULT NOW(),
    
    CONSTRAINT chk_porcentaje CHECK (porcentaje_afectacion >= 0 AND porcentaje_afectacion <= 100)
);

CREATE INDEX idx_intersecciones_parcela ON intersecciones_afecciones(parcela_id);
CREATE INDEX idx_intersecciones_geom ON intersecciones_afecciones USING GIST(geom_interseccion);
CREATE INDEX idx_intersecciones_capa ON intersecciones_afecciones(capa_nombre);

-- ============================================================
-- 5. TABLA: capas_vectoriales
--    Catálogo de capas disponibles
-- ============================================================

CREATE TABLE IF NOT EXISTS capas_vectoriales (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(100) UNIQUE NOT NULL,
    descripcion TEXT,
    
    -- Ubicación
    ruta_gpkg TEXT,
    layer_name VARCHAR(100),
    
    -- Clasificación
    categoria VARCHAR(50),  -- proteccion, urbanismo, infraestructura, riesgo
    tipo_geometria VARCHAR(20),
    campo_clasificacion VARCHAR(100),
    
    -- Sistema de coordenadas
    srid INTEGER DEFAULT 25830,
    
    -- Leyenda (colores y etiquetas)
    leyenda_json JSONB,
    
    -- Estado
    activa BOOLEAN DEFAULT TRUE,
    fecha_actualizacion TIMESTAMP,
    
    -- Metadatos
    fuente_datos VARCHAR(200),
    licencia VARCHAR(100),
    fecha_datos DATE
);

CREATE INDEX idx_capas_nombre ON capas_vectoriales(nombre);
CREATE INDEX idx_capas_categoria ON capas_vectoriales(categoria);

-- ============================================================
-- 6. TABLA: lotes_procesamiento
--    Gestión de procesamiento por lotes
-- ============================================================

CREATE TABLE IF NOT EXISTS lotes_procesamiento (
    id SERIAL PRIMARY KEY,
    lote_id VARCHAR(50) UNIQUE NOT NULL,
    
    -- Referencias del lote
    referencias_array TEXT[],
    total_referencias INTEGER,
    
    -- Estado del procesamiento
    estado VARCHAR(20) DEFAULT 'pendiente',  -- pendiente, procesando, completado, error
    referencias_procesadas INTEGER DEFAULT 0,
    referencias_exitosas INTEGER DEFAULT 0,
    referencias_fallidas INTEGER DEFAULT 0,
    
    -- Tiempos
    fecha_inicio TIMESTAMP DEFAULT NOW(),
    fecha_fin TIMESTAMP,
    tiempo_total_segundos INTEGER,
    
    -- Resultados
    resultado_json JSONB,
    
    -- Usuario/sistema
    usuario VARCHAR(100),
    ip_origen VARCHAR(45)
);

CREATE INDEX idx_lotes_id ON lotes_procesamiento(lote_id);
CREATE INDEX idx_lotes_estado ON lotes_procesamiento(estado);
CREATE INDEX idx_lotes_fecha ON lotes_procesamiento(fecha_inicio);

-- ============================================================
-- 7. VISTA: resumen_parcelas
--    Vista consolidada de información de parcelas
-- ============================================================

CREATE OR REPLACE VIEW resumen_parcelas AS
SELECT 
    p.id,
    p.referencia_catastral,
    p.municipio,
    p.area_catastral,
    p.uso_principal,
    p.fecha_consulta,
    
    -- Análisis urbanístico (si existe)
    au.clasificacion_suelo,
    au.edificabilidad,
    au.ocupacion_maxima,
    au.afecciones_detectadas,
    
    -- Número de afecciones
    COUNT(ia.id) as num_afecciones,
    
    -- Área total afectada
    SUM(ia.area_interseccion) as area_total_afectada,
    
    -- Porcentaje máximo de afectación
    MAX(ia.porcentaje_afectacion) as max_porcentaje_afectacion
    
FROM parcelas_catastro p
LEFT JOIN analisis_urbanistico au ON p.id = au.parcela_id
LEFT JOIN intersecciones_afecciones ia ON p.id = ia.parcela_id
GROUP BY 
    p.id, p.referencia_catastral, p.municipio, p.area_catastral, 
    p.uso_principal, p.fecha_consulta, au.clasificacion_suelo, 
    au.edificabilidad, au.ocupacion_maxima, au.afecciones_detectadas;

-- ============================================================
-- 8. FUNCIONES ÚTILES
-- ============================================================

-- Función: Calcular intersección con todas las capas configuradas
CREATE OR REPLACE FUNCTION calcular_afecciones_parcela(
    p_parcela_id INTEGER
) RETURNS TABLE (
    capa VARCHAR,
    area_interseccion NUMERIC,
    porcentaje NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        ia.capa_nombre::VARCHAR,
        ia.area_interseccion,
        ia.porcentaje_afectacion
    FROM intersecciones_afecciones ia
    WHERE ia.parcela_id = p_parcela_id
    ORDER BY ia.porcentaje_afectacion DESC;
END;
$$ LANGUAGE plpgsql;

-- Función: Limpiar análisis antiguos
CREATE OR REPLACE FUNCTION limpiar_analisis_antiguos(dias INTEGER DEFAULT 90)
RETURNS INTEGER AS $$
DECLARE
    filas_eliminadas INTEGER;
BEGIN
    DELETE FROM intersecciones_afecciones
    WHERE fecha_calculo < NOW() - INTERVAL '1 day' * dias;
    
    GET DIAGNOSTICS filas_eliminadas = ROW_COUNT;
    RETURN filas_eliminadas;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 9. TRIGGERS
-- ============================================================

-- Trigger: Actualizar área catastral automáticamente
CREATE OR REPLACE FUNCTION actualizar_area_parcela()
RETURNS TRIGGER AS $$
BEGIN
    NEW.area_catastral := ST_Area(NEW.geom);
    NEW.perimetro := ST_Perimeter(NEW.geom);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_actualizar_area
BEFORE INSERT OR UPDATE OF geom ON parcelas_catastro
FOR EACH ROW
EXECUTE FUNCTION actualizar_area_parcela();

-- Trigger: Actualizar timestamp en modificación
CREATE OR REPLACE FUNCTION actualizar_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.fecha_actualizacion := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_actualizar_timestamp_parcela
BEFORE UPDATE ON parcelas_catastro
FOR EACH ROW
EXECUTE FUNCTION actualizar_timestamp();

-- ============================================================
-- 10. DATOS INICIALES
-- ============================================================

INSERT INTO capas_vectoriales (nombre, descripcion, categoria, tipo_geometria, activa) VALUES
('protecciones', 'Espacios naturales protegidos', 'proteccion', 'Polygon', TRUE),
('planeamiento', 'Planeamiento urbanístico municipal', 'urbanismo', 'Polygon', TRUE),
('infraestructuras', 'Líneas eléctricas y gasoductos', 'infraestructura', 'LineString', TRUE),
('servidumbres', 'Servidumbres legales (costas, carreteras)', 'servidumbre', 'Polygon', TRUE),
('riesgos', 'Zonas de riesgo (inundación, incendio)', 'riesgo', 'Polygon', TRUE)
ON CONFLICT (nombre) DO NOTHING;

-- ============================================================
-- FIN DEL ESQUEMA
-- ============================================================

-- Verificar instalación
SELECT 'PostGIS Version: ' || PostGIS_Version();
SELECT 'Tablas creadas: ' || COUNT(*) FROM information_schema.tables 
WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
