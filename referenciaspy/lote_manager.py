#!/usr/bin/env python3
"""
catastro/lote_manager.py
Gestor de procesamiento de lotes de referencias catastrales
"""

import json
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class LoteManager:
    """
    Gestiona el procesamiento de múltiples referencias catastrales
    Mantiene estado y genera reportes de progreso
    """
    
    def __init__(self, output_dir: str = "outputs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Estado de lotes
        self.lotes_dir = self.output_dir / "_lotes"
        self.lotes_dir.mkdir(exist_ok=True)
        
        self.lote_id = None
        self.estado_actual = {}
    
    def generar_lote_id(self) -> str:
        """Genera ID único para el lote"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"lote_{timestamp}"
    
    def guardar_estado(self, lote_id: str, estado: dict):
        """Guarda estado del lote en archivo JSON"""
        try:
            estado_path = self.lotes_dir / f"{lote_id}_estado.json"
            with open(estado_path, 'w', encoding='utf-8') as f:
                json.dump(estado, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error guardando estado: {e}")
    
    def obtener_estado(self, lote_id: str) -> Optional[dict]:
        """Recupera estado de un lote"""
        try:
            estado_path = self.lotes_dir / f"{lote_id}_estado.json"
            if estado_path.exists():
                with open(estado_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error leyendo estado: {e}")
        return None
    
    def procesar_lista(
        self, 
        referencias: List[str], 
        downloader, 
        analyzer=None, 
        pdf_gen=None
    ) -> Dict:
        """
        Procesa una lista de referencias catastrales
        
        Args:
            referencias: Lista de referencias a procesar
            downloader: Instancia de CatastroDownloader
            analyzer: Instancia de VectorAnalyzer (opcional)
            pdf_gen: Instancia de AfeccionesPDF (opcional)
        
        Returns:
            dict: Resumen del procesamiento
        """
        self.lote_id = self.generar_lote_id()
        logger.info(f"📦 Iniciando lote: {self.lote_id}")
        
        total = len(referencias)
        resultados = {
            "lote_id": self.lote_id,
            "fecha_inicio": datetime.now().isoformat(),
            "total_referencias": total,
            "procesadas": 0,
            "exitosas": 0,
            "fallidas": 0,
            "referencias": {}
        }
        
        # Guardar estado inicial
        self.guardar_estado(self.lote_id, resultados)
        
        for idx, ref in enumerate(referencias, 1):
            ref_limpia = ref.replace(' ', '').strip().upper()
            logger.info(f"\n[{idx}/{total}] Procesando: {ref_limpia}")
            
            resultado_ref = {
                "referencia": ref_limpia,
                "estado": "procesando",
                "inicio": datetime.now().isoformat(),
                "archivos": {}
            }
            
            try:
                # 1. Descargar datos catastrales
                logger.info("  📥 Descargando datos...")
                exito, zip_path = downloader.descargar_todo_completo(ref_limpia)
                
                if exito:
                    resultado_ref["estado"] = "exitoso"
                    resultado_ref["zip"] = str(zip_path) if zip_path else None
                    
                    # Recopilar archivos generados
                    ref_dir = self.output_dir / ref_limpia
                    resultado_ref["archivos"] = self._recopilar_archivos(ref_dir)
                    
                    # 2. Análisis de afecciones (DEACTIVADO por defecto)
                    # Desactivado para mejorar rendimiento en lotes grandes
                    # Para activar, cambiar ANALISIS_AFECCIONES_ACTIVO = True
                    ANALISIS_AFECCIONES_ACTIVO = True
                    
                    if ANALISIS_AFECCIONES_ACTIVO and analyzer:
                        logger.info("  🔍 Analizando afecciones...")
                        try:
                            gml_path = ref_dir / "gml" / f"{ref_limpia}_parcela.gml"
                            if gml_path.exists():
                                afecciones = analyzer.analizar(
                                    gml_path,
                                    "afecciones_totales.gpkg",
                                    "tipo"
                                )
                                resultado_ref["afecciones"] = afecciones
                                logger.info("    ✅ Afecciones analizadas")
                        except Exception as e:
                            logger.warning(f"    ⚠️ Error analizando afecciones: {e}")
                    else:
                        logger.info(f"  📋 Análisis de afecciones desactivado para {ref_limpia}")
                        resultado_ref["afecciones"] = {
                            "detalle": {},
                            "total": 0.0,
                            "area_total_m2": 0.0,
                            "afecciones_detectadas": False,
                            "mensaje": "Análisis de afecciones desactivado. Use el panel 'Análisis Afecciones' para análisis manual."
                        }
                    
                    # 3. Generar PDF (si está disponible)
                    if pdf_gen and analyzer:
                        logger.info("  📄 Generando PDF...")
                        try:
                            mapas = []
                            images_dir = ref_dir / "images"
                            if images_dir.exists():
                                for img in images_dir.glob(f"{ref_limpia}*zoom4*.png"):
                                    mapas.append(str(img))
                                    break
                            
                            afecciones = resultado_ref.get("afecciones", {})
                            
                            pdf_path = pdf_gen.generar(
                                referencia=ref_limpia,
                                resultados=afecciones,
                                mapas=mapas,
                                incluir_tabla=bool(afecciones)
                            )
                            
                            if pdf_path:
                                resultado_ref["archivos"]["pdf_informe"] = str(pdf_path)
                                logger.info("    ✅ PDF generado")
                        except Exception as e:
                            logger.warning(f"    ⚠️ Error generando PDF: {e}")
                    
                    resultados["exitosas"] += 1
                    logger.info(f"  ✅ {ref_limpia} completado")
                    
                else:
                    resultado_ref["estado"] = "error"
                    resultado_ref["error"] = "No se pudieron descargar los datos"
                    resultados["fallidas"] += 1
                    logger.error(f"  ❌ {ref_limpia} falló")
                
            except Exception as e:
                resultado_ref["estado"] = "error"
                resultado_ref["error"] = str(e)
                resultados["fallidas"] += 1
                logger.error(f"  ❌ Error en {ref_limpia}: {e}")
            
            finally:
                resultado_ref["fin"] = datetime.now().isoformat()
                resultados["referencias"][ref_limpia] = resultado_ref
                resultados["procesadas"] += 1
                
                # Actualizar estado
                self.guardar_estado(self.lote_id, resultados)
                
                # Pausa entre referencias
                if idx < total:
                    time.sleep(1)
        
        # Estado final
        resultados["fecha_fin"] = datetime.now().isoformat()
        resultados["estado"] = "completado"
        self.guardar_estado(self.lote_id, resultados)
        
        # Generar resumen
        self._generar_resumen_html(resultados)
        
        logger.info(f"\n{'='*70}")
        logger.info(f"📊 LOTE COMPLETADO: {self.lote_id}")
        logger.info(f"{'='*70}")
        logger.info(f"  ✅ Exitosas: {resultados['exitosas']}/{total}")
        logger.info(f"  ❌ Fallidas: {resultados['fallidas']}/{total}")
        logger.info(f"{'='*70}\n")
        
        return resultados
    
    def _recopilar_archivos(self, ref_dir: Path) -> Dict:
        """Recopila información de archivos generados"""
        archivos = {
            "gml_parcela": None,
            "gml_edificio": None,
            "ficha_catastral": None,
            "imagenes": [],
            "json": [],
            "html": []
        }
        
        if not ref_dir.exists():
            return archivos
        
        # GML
        gml_dir = ref_dir / "gml"
        if gml_dir.exists():
            for gml in gml_dir.glob("*.gml"):
                if "parcela" in gml.name:
                    archivos["gml_parcela"] = str(gml)
                elif "edificio" in gml.name:
                    archivos["gml_edificio"] = str(gml)
        
        # PDFs
        pdf_dir = ref_dir / "pdf"
        if pdf_dir.exists():
            for pdf in pdf_dir.glob("*.pdf"):
                if "ficha_catastral" in pdf.name:
                    archivos["ficha_catastral"] = str(pdf)
        
        # Imágenes
        images_dir = ref_dir / "images"
        if images_dir.exists():
            archivos["imagenes"] = [str(img) for img in images_dir.glob("*.png")]
        
        # JSON
        json_dir = ref_dir / "json"
        if json_dir.exists():
            archivos["json"] = [str(j) for j in json_dir.glob("*.json")]
        
        # HTML
        html_dir = ref_dir / "html"
        if html_dir.exists():
            archivos["html"] = [str(h) for h in html_dir.glob("*.html")]
        
        return archivos
    
    def _generar_resumen_html(self, resultados: Dict):
        """Genera resumen HTML del lote"""
        try:
            lote_id = resultados["lote_id"]
            html_path = self.lotes_dir / f"{lote_id}_resumen.html"
            
            html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Resumen Lote {lote_id}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; }}
        h1 {{ color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }}
        .stats {{ display: flex; gap: 20px; margin: 20px 0; }}
        .stat-card {{ flex: 1; padding: 20px; border-radius: 8px; text-align: center; }}
        .stat-card.success {{ background: #4CAF50; color: white; }}
        .stat-card.error {{ background: #f44336; color: white; }}
        .stat-card.total {{ background: #2196F3; color: white; }}
        .stat-number {{ font-size: 48px; font-weight: bold; }}
        .stat-label {{ font-size: 14px; margin-top: 5px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #f0f0f0; font-weight: bold; }}
        .exitoso {{ color: #4CAF50; }}
        .error {{ color: #f44336; }}
        .badge {{ padding: 4px 8px; border-radius: 4px; font-size: 12px; }}
        .badge.success {{ background: #4CAF50; color: white; }}
        .badge.fail {{ background: #f44336; color: white; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📦 Resumen Lote: {lote_id}</h1>
        
        <div class="stats">
            <div class="stat-card total">
                <div class="stat-number">{resultados['total_referencias']}</div>
                <div class="stat-label">Total Referencias</div>
            </div>
            <div class="stat-card success">
                <div class="stat-number">{resultados['exitosas']}</div>
                <div class="stat-label">Exitosas</div>
            </div>
            <div class="stat-card error">
                <div class="stat-number">{resultados['fallidas']}</div>
                <div class="stat-label">Fallidas</div>
            </div>
        </div>
        
        <h2>Detalle de Referencias</h2>
        <table>
            <thead>
                <tr>
                    <th>Referencia</th>
                    <th>Estado</th>
                    <th>Archivos Generados</th>
                </tr>
            </thead>
            <tbody>
"""
            
            for ref, datos in resultados["referencias"].items():
                estado_badge = "success" if datos["estado"] == "exitoso" else "fail"
                estado_texto = "✅ Exitoso" if datos["estado"] == "exitoso" else "❌ Error"
                
                archivos = datos.get("archivos", {})
                num_archivos = sum([
                    1 if archivos.get("gml_parcela") else 0,
                    1 if archivos.get("ficha_catastral") else 0,
                    len(archivos.get("imagenes", [])),
                    len(archivos.get("json", []))
                ])
                
                html += f"""
                <tr>
                    <td><strong>{ref}</strong></td>
                    <td><span class="badge {estado_badge}">{estado_texto}</span></td>
                    <td>{num_archivos} archivos</td>
                </tr>
"""
            
            html += """
            </tbody>
        </table>
        
        <p style="text-align: center; color: #666; margin-top: 40px;">
            Generado automáticamente por Suite Tasación dnogares
        </p>
    </div>
</body>
</html>
"""
            
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html)
            
            logger.info(f"📄 Resumen HTML generado: {html_path}")
            
        except Exception as e:
            logger.error(f"Error generando resumen HTML: {e}")


# Testing
if __name__ == "__main__":
    import sys
    
    # Simulación - sin referencias de prueba
    referencias = []  # Agrega aquí tus referencias reales
    
    manager = LoteManager()
    print(f"📦 Lote ID: {manager.generar_lote_id()}")
    print(f"📁 Directorio lotes: {manager.lotes_dir}")
    
    if referencias:
        print(f"📋 Procesando {len(referencias)} referencias...")
        # Aquí iría el procesamiento real
    else:
        print("📝 No hay referencias configuradas. Agrega tus referencias reales.")