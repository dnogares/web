import os
import json
import geopandas as gpd
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

class GISDatabase:
    def __init__(self):
        # 1. Load config from JSON if available (as fallback)
        config_db = {}
        try:
            if os.path.exists("config_web.json"):
                with open("config_web.json", "r") as f:
                    config = json.load(f)
                    config_db = config.get("database", {})
        except Exception as e:
            print(f"Warning: Could not load config_web.json: {e}")

        # 2. Set attributes with priority: Env Var > Config File > Default
        self.host = os.getenv("POSTGIS_HOST", config_db.get("host", "localhost"))
        self.port = os.getenv("POSTGIS_PORT", config_db.get("port", "5432"))
        self.database = os.getenv("POSTGIS_DATABASE", config_db.get("dbname", "GIS"))
        self.user = os.getenv("POSTGIS_USER", config_db.get("user", "manuel"))
        self.password = os.getenv("POSTGIS_PASSWORD", config_db.get("password", "Aa123456"))
        
        # Handle 'postgis' hostname which might be used in Docker
        if self.host == "postgis":
            # Just to be safe, though usually DNS handles it
            pass
            
        self.db_url = f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
        try:
            self.engine = create_engine(self.db_url, pool_pre_ping=True)
        except Exception as e:
            print(f"Error creating engine: {e}")
            self.engine = None

    def test_connection(self):
        if not self.engine:
            return False
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            # Handle potential encoding errors when printing exception on Windows
            try:
                msg = str(e)
                print(f"Database connection error: {msg}")
            except Exception:
                print("Database connection error: (could not decode error message)")
            return False

    def get_available_layers(self, schemas=["capas", "public"]):
        if not self.engine:
            return []
        
        all_layers = []
        
        # Ensure schemas is a list
        if isinstance(schemas, str):
            schemas = [schemas]
            
        sql = text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = :schema
            AND table_type = 'BASE TABLE'
        """)
        
        try:
            with self.engine.connect() as conn:
                for schema in schemas:
                    result = conn.execute(sql, {"schema": schema})
                    for row in result:
                        table_name = row[0]
                        all_layers.append({
                            "name": table_name,
                            "schema": schema,
                            "full_name": f"{schema}.{table_name}"
                        })
            return all_layers
        except Exception as e:
            print(f"Error listing layers: {e}")
            return []

    def query_intersection(self, schema, table, wkt_geom, srid=25830):
        """
        Consulta intersección espacial devolviendo GeoDataFrame.
        Asume que la tabla tiene columna 'geom'.
        """
        if not self.engine:
            return gpd.GeoDataFrame()
            
        # Construir consulta
        # Se asume que la geometría de entrada es WKT en EPSG:4326 o el mismo de la base
        # Pero procesar_parcelas pasa wkt de 4326 usualmente si viene de gml
        
        # Nota: ST_GeomFromText(..., 4326)
        
        sql = text(f"""
            SELECT *
            FROM {schema}.{table}
            WHERE ST_Intersects(geom, ST_Transform(ST_GeomFromText(:wkt, 4326), ST_SRID(geom)))
        """)
        
        try:
            gdf = gpd.read_postgis(sql, self.engine, params={"wkt": wkt_geom}, geom_col="geom")
            return gdf
        except Exception as e:
            # print(f"Error querying intersection for {table}: {e}")
            return gpd.GeoDataFrame()
