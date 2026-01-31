import os
import json
import zipfile
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional
import logging
import geopandas as gpd
from shapely.geometry import Polygon, Point
logger = logging.getLogger(__name__)
class CatastroDownloader:
    BASE_URL = "https://ovc.catastro.minhafp.gob.es/ovc/Proxy.ashx"
    GEO_URL = "https://ovc.catastro.minhafp.gob.es/ovc/Geo.ashx"
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"[CatastroDownloader] Inicializado en: {self.output_dir}")
    def consultar_referencia(self, referencia: str) -> Dict:
        params = {"SRS": "EPSG:4326", "refcat": referencia, "format": "json"}
        try:
            response = requests.get(self.BASE_URL, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                return {"success": True, "data": data, "referencia": referencia, "timestamp": datetime.now().isoformat()}
            return {"success": False, "error": f"Error HTTP {response.status_code}", "referencia": referencia}
        except Exception as e:
            return {"success": False, "error": str(e), "referencia": referencia}
    def descargar_geometria(self, referencia: str) -> Optional[str]:
        try:
            geojson_url = f"{self.GEO_URL}?refcat={referencia}&format=geojson"
            response = requests.get(geojson_url, timeout=30)
            if response.status_code == 200:
                geojson_path = self.output_dir / f"{referencia}.geojson"
                content = response.text
                if content and len(content) > 10:
                    with open(geojson_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    return str(geojson_path)
            return None
        except Exception as e:
            logger.error(f"[CatastroDownloader] Error: {e}")
            return None