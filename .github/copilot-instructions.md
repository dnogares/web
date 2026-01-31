# Copilot Instructions for Catastro Web GIS Project

## Project Overview

This is a **hybrid GIS platform** combining cadastral analysis (Spanish property registry) with geospatial web services. Two codebases coexist:

1. **web6/** - FastAPI server + cadastral downloading + spatial analysis (PostGIS-optional)
2. **files/proyecto_gis/** - High-performance web GIS API using FlatGeobuf streaming

### Key Architecture Pattern

```
User Request → FastAPI Route → Specialized Module → Data Source
                                  (catastro4.py)          ├─ Catastro WFS
                                  (afecciones.py)         ├─ PostGIS (optional)
                                  (urbanismo.py)          ├─ FlatGeobuf files
                                  (gis_db.py)             └─ WMS services
```

## Critical Components & Data Flows

### 1. **Cadastral Download Pipeline** (`catastro4.py`)
- **Purpose**: Fetch property data from Spanish Catastro WFS service
- **Key pattern**: HTTP caching via `requests_cache` to avoid rate limits
- **Exports**: XML/ZIP → CSV/Shapefile/KML with coordinate unification
- **When modifying**: Always preserve cache logic; test with `check_gis.py` before deploying

### 2. **Spatial Analysis** (`afecciones.py`)
- **Smart fallback architecture**: Tries PostGIS first, falls back to Shapefile + WMS if DB unavailable
- **Config location**: `config_web.json` → `database.*` contains connection params
- **GIS intersection logic**: Uses PostGIS `ST_Intersects` or GeoPandas `gpd.overlay()`
- **Important**: Threshold filter set to 0.01% to exclude noise; adjust in line ~85 if changing detection sensitivity

### 3. **PostGIS Database Layer** (`gis_db.py`)
- **Singleton pattern**: `db_gis` in `main.py` reuses connection pool to avoid exhaustion
- **Pool config**: `pool_size=10, max_overflow=20, pool_timeout=30, pool_recycle=1800`
- **Schemas expected**: `afecciones.*` tables (Red Natura, Vías Pecuarias, etc.)
- **Error handling**: Gracefully degrades if DB unavailable — always test with `test_db_gis.py`

### 4. **FastAPI Server Initialization** (`main.py`)
- **Route structure**: Routes in `/api/routes/` but also inline in `main.py`
- **Startup checks**: Tests availability of catastro4, urbanismo, afecciones, geopandas modules
- **CORS enabled** for cross-origin requests
- **Static files**: Served from `static/` directory with Glassmorphism UI

### 5. **Data Source Abstraction** (`proyecto_gis/services/data_source_manager.py`)
- **In files/ codebase**: Handles FlatGeobuf streaming + PostGIS queries
- **HTTP Range Requests**: Only fetches bbox-visible features from `.fgb` files (20x speedup)
- **Configuration**: Database credentials in `config_web.json` (same config used by both codebases)

## Project-Specific Conventions

### Error Handling
- **Pattern**: Log with 🔗/⚠️/✅ emoji prefixes (see `gis_db.py` line 5)
- **DB failures**: Never crash; always provide fallback behavior
- **API responses**: Return `{"error": "..."}` JSON on failure, HTTP 500 status

### Configuration Management
- **Single source of truth**: `config_web.json` contains all paths + DB credentials
- **File encodings**: Handle UTF-8 + Latin-1 fallback (see `gis_db.py` line 27)
- **Validation**: Always test DB connection before running analyses

### Import Strategy
- **Optional dependencies**: Check `try/except ImportError` blocks in `main.py` (lines 30-105)
- **Graceful degradation**: Missing geopandas → no spatial analysis, missing referenciaspy → basic features only
- **Module availability flags**: `CATASTRO_AVAILABLE`, `GEOPANDAS_AVAILABLE`, etc. control feature availability

### GIS Coordinate Systems
- **Web data**: Always WGS84 (EPSG:4326)
- **Analysis**: Project to metric CRS (EPSG:25830 for Spain UTM30N) for area calculations
- **Conversions**: Use `geopandas.to_crs()` or PostGIS ST_Transform (never manual math)

### Database Queries
- **Pattern**: Use parameterized queries with `text()` from SQLAlchemy (line 7 in `gis_db.py`)
- **Geometry WKT**: Pass geometries as WKT strings to DB queries
- **Connection pooling**: Reuse engine singleton, never open new connections in loops

## Common Development Tasks

### Add a New Analysis Module
1. Create `new_module.py` in root
2. Add `try/except` import block in `main.py` with availability flag
3. Create FastAPI route handler returning JSON response
4. Add to `config.json` if it needs external service URLs
5. Test fallback behavior when module unavailable

### Enable PostGIS Analysis
1. Ensure PostgreSQL + PostGIS installed
2. Create schema: `psql -d GIS -c "CREATE SCHEMA afecciones;"`
3. Import your layers: `python sync_mapama.py` (or use QGIS)
4. Update `config_web.json` database credentials
5. Run `test_db_gis.py` to verify connection
6. Analysis routes will auto-detect DB and use SQL instead of files

### Export Geospatial Data
1. **To FlatGeobuf**: `python scripts/convert_to_fgb.py` (in files/proyecto_gis)
   - Creates streaming-friendly files for web delivery
2. **To Shapefile**: `catastro4.py` does this automatically on downloads
3. **To KML**: `catastro4.py` generates for Google Earth visualization

### Debug Data Access Issues
1. **Cadastral WFS failing**: Check network in `test_descarga.py`, may be rate-limited
2. **DB connection failing**: Run `test_db_gis.py` to diagnose PostgreSQL issues
3. **Missing layers**: Check `layers_found.json` to see what was auto-detected
4. **Performance slow**: Profile with `check_gis_perf.py`, check indexes in PostGIS

## Integration Points & External Services

### Spanish Government Services
- **Catastro WFS**: `https://www.catastro.minhaf.es/cartografia/web` (property data)
- **IGN PNOA**: Orthophoto WMS service for map context
- **MAPAMA**: Environmental constraints integration (see `sync_mapama.py`)

### PostGIS-Specific Behaviors
- **Timeout**: 30 seconds per query (pool_timeout)
- **Connection recycling**: Every 30 minutes (pool_recycle=1800)
- **Max connections**: 30 total (pool_size 10 + overflow 20)
- **Spatial index**: Assumes GIST indexes exist on geometry columns

## Testing Strategy

### Unit Tests
- `test_db_gis.py` - Database connectivity
- `test_descarga.py` - Cadastral downloads
- `test_afecciones_api.py` - Spatial intersection logic
- `test_sintaxis.py` - Module import validation

### Performance Benchmarks
- `check_gis_perf.py` - Query execution times
- `check_gis.py` - Layer loading performance
- FlatGeobuf HTTP Range Requests: Expect <0.1s for visible bbox

### Manual Testing
1. Start server: `uvicorn main:app --reload`
2. Test cadastral route: Visit `/api/cadastral?referencia=12345678AB`
3. Test afecciones: POST `/api/afecciones` with reference
4. Check logs for emoji-prefixed status messages

## File Organization

```
web6/
├── main.py                  # FastAPI app + startup checks
├── catastro4.py             # Cadastral WFS download + cache
├── afecciones.py            # Spatial intersection analysis
├── urbanismo.py             # Planning compatibility checks
├── gis_db.py                # PostGIS connection pooling
├── config_web.json          # Database + service URLs
├── requirements.txt         # Dependencies
├── api/routes/              # API endpoint definitions
├── static/                  # Frontend (HTML/CSS/JS)
├── capas/                   # Local GIS files (SHP/GPKG)
└── test_*.py                # Test suites
```

## Common Gotchas

1. **Encoding issues**: Always specify `encoding="utf-8"` when reading config files (see line 27 in gis_db.py)
2. **Geometry precision**: ST_Intersects is binary (no area threshold); use ST_Area() separately for percentage checks
3. **CRS mixing**: Never compare areas without projecting to metric CRS first
4. **Database credentials**: Are in `config_web.json` — ensure Git ignores it or use environment variables
5. **Concurrent downloads**: catastro4.py uses ThreadPoolExecutor with `max_workers=3` (config.json) — don't increase without load testing
6. **WFS rate limiting**: Catastro service blocks after ~30 requests/minute; HTTP cache essential
7. **PostGIS timeouts**: Long-running spatial operations (>30s) will fail; optimize queries or increase pool_timeout

## Key Files to Reference

- **Architecture overview**: [README.md](README.md) + [README_MAPAMA_INTEGRATION.md](README_MAPAMA_INTEGRATION.md)
- **API examples**: [main.py](main.py) lines 200-500
- **Database integration**: [gis_db.py](gis_db.py)
- **Spatial analysis example**: [afecciones.py](afecciones.py) lines 50-100
- **Module availability checks**: [main.py](main.py) lines 30-105
