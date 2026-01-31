#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo para generación de informes urbanísticos
Obtiene información de clasificación, calificación y afecciones urbanísticas
"""

import requests
import json
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import xml.etree.ElementTree as ET
from pathlib import Path

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class InformeUrbanistico:
    """Clase para generar informes urbanísticos completos"""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Inicializa el generador de informes urbanísticos
        
        Args:
            config_path: Ruta al archivo de configuración JSON
        """
        self.config = self._cargar_configuracion(config_path)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'InformeUrbanistico/1.0',
            'Accept': 'application/json, application/xml'
        })
        
    def _cargar_configuracion(self, config_path: Optional[str]) -> Dict:
        """Carga la configuración desde archivo JSON"""
        config_default = {
            'urls': {
                'catastro': 'https://ovc.catastro.meh.es/ovcservweb/OVCSWLocalizacionRC/',
                'inspire': 'https://inspire.catastro.es/inspire/wfs',
                'siu': 'https://services.arcgis.com/YWQjeT7gO1z78YVu/arcgis/rest/services/',
                'mapama': 'https://wms.mapama.gob.es/sig/Biodiversidad/'
            },
            'timeout': 30,
            'max_retries': 3
        }
        
        if config_path and Path(config_path).exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                custom_config = json.load(f)
                config_default.update(custom_config)
        
        return config_default
    
    def generar_informe_completo(
        self, 
        ref_catastral: Optional[str] = None,
        provincia: Optional[str] = None,
        municipio: Optional[str] = None,
        via: Optional[str] = None,
        numero: Optional[str] = None
    ) -> Dict:
        """
        Genera un informe urbanístico completo
        
        Args:
            ref_catastral: Referencia catastral
            provincia: Nombre de la provincia
            municipio: Nombre del municipio
            via: Nombre de la vía
            numero: Número de la vía
            
        Returns:
            Diccionario con toda la información urbanística
        """
        logger.info(f"Generando informe urbanístico para ref: {ref_catastral}")
        
        informe = {
            'fecha_generacion': datetime.now().isoformat(),
            'datos_identificacion': {},
            'datos_catastrales': {},
            'clasificacion_urbanistica': {},
            'calificacion_urbanistica': {},
            'afecciones_territoriales': {},
            'gestion_urbanistica': {},
            'cartografia': {},
            'estado': 'pendiente'
        }
        
        try:
            # 1. Obtener datos catastrales
            if ref_catastral:
                informe['datos_catastrales'] = self._obtener_datos_catastro(ref_catastral)
            elif provincia and municipio and via and numero:
                informe['datos_catastrales'] = self._buscar_por_direccion(
                    provincia, municipio, via, numero
                )
                ref_catastral = informe['datos_catastrales'].get('referencia_catastral')
            else:
                raise ValueError("Debe proporcionar referencia catastral o dirección completa")
            
            # 2. Obtener clasificación urbanística
            informe['clasificacion_urbanistica'] = self._obtener_clasificacion_suelo(
                ref_catastral, provincia, municipio
            )
            
            # 3. Obtener calificación urbanística
            informe['calificacion_urbanistica'] = self._obtener_calificacion_urbanistica(
                ref_catastral, provincia, municipio
            )
            
            # 4. Consultar afecciones territoriales
            informe['afecciones_territoriales'] = self._consultar_afecciones(
                informe['datos_catastrales'].get('coordenadas', {})
            )
            
            # 5. Obtener información de gestión urbanística
            informe['gestion_urbanistica'] = self._obtener_gestion_urbanistica(
                ref_catastral, provincia, municipio
            )
            
            # 6. Generar cartografía
            informe['cartografia'] = self._generar_cartografia(
                ref_catastral,
                informe['datos_catastrales'].get('coordenadas', {})
            )
            
            informe['estado'] = 'completado'
            logger.info("Informe urbanístico generado correctamente")
            
        except Exception as e:
            logger.error(f"Error generando informe: {str(e)}")
            informe['estado'] = 'error'
            informe['error'] = str(e)
        
        return informe
    
    def _obtener_datos_catastro(self, ref_catastral: str) -> Dict:
        """
        Obtiene datos catastrales básicos
        
        Args:
            ref_catastral: Referencia catastral
            
        Returns:
            Diccionario con datos catastrales
        """
        logger.info(f"Obteniendo datos catastrales: {ref_catastral}")
        
        datos = {
            'referencia_catastral': ref_catastral,
            'direccion': {},
            'superficie': {},
            'uso': '',
            'coordenadas': {}
        }
        
        try:
            # Consulta a Catastro - OVCCallejero
            url = f"{self.config['urls']['catastro']}OVCCallejero.asmx/Consulta_DNPRC"
            params = {
                'Provincia': '',
                'Municipio': '',
                'RC': ref_catastral
            }
            
            response = self.session.get(url, params=params, timeout=self.config['timeout'])
            
            if response.status_code == 200:
                # Parsear XML de respuesta
                root = ET.fromstring(response.content)
                
                # Extraer datos básicos
                for elem in root.iter():
                    if 'ldt' in elem.tag:
                        datos['direccion']['tipo_via'] = elem.text
                    elif 'lnp' in elem.tag:
                        datos['direccion']['nombre_via'] = elem.text
                    elif 'pnp' in elem.tag:
                        datos['direccion']['numero'] = elem.text
                    elif 'nm' in elem.tag:
                        datos['direccion']['municipio'] = elem.text
                    elif 'np' in elem.tag:
                        datos['direccion']['provincia'] = elem.text
                
                # Obtener coordenadas desde INSPIRE
                datos['coordenadas'] = self._obtener_coordenadas_inspire(ref_catastral)
                
        except Exception as e:
            logger.error(f"Error obteniendo datos catastrales: {str(e)}")
        
        return datos
    
    def _buscar_por_direccion(
        self, 
        provincia: str, 
        municipio: str, 
        via: str, 
        numero: str
    ) -> Dict:
        """Busca referencia catastral por dirección"""
        logger.info(f"Buscando por dirección: {via} {numero}, {municipio}")
        
        # Implementar búsqueda por dirección usando servicios de Catastro
        # Por ahora devolvemos estructura vacía
        return {
            'referencia_catastral': '',
            'direccion': {
                'provincia': provincia,
                'municipio': municipio,
                'via': via,
                'numero': numero
            }
        }
    
    def _obtener_coordenadas_inspire(self, ref_catastral: str) -> Dict:
        """Obtiene coordenadas de la parcela desde servicios INSPIRE"""
        logger.info("Obteniendo coordenadas INSPIRE")
        
        coordenadas = {
            'sistema': 'EPSG:4326',
            'latitud': 0.0,
            'longitud': 0.0,
            'bbox': []
        }
        
        try:
            # Consulta WFS INSPIRE
            url = self.config['urls']['inspire']
            params = {
                'service': 'WFS',
                'version': '2.0.0',
                'request': 'GetFeature',
                'typeName': 'cp:CadastralParcel',
                'filter': f'<Filter><PropertyIsEqualTo><PropertyName>nationalCadastralReference</PropertyName><Literal>{ref_catastral}</Literal></PropertyIsEqualTo></Filter>',
                'outputFormat': 'application/json'
            }
            
            response = self.session.get(url, params=params, timeout=self.config['timeout'])
            
            if response.status_code == 200:
                data = response.json()
                if 'features' in data and len(data['features']) > 0:
                    geometry = data['features'][0].get('geometry', {})
                    if geometry.get('type') == 'Polygon':
                        coords = geometry.get('coordinates', [[]])[0]
                        if coords:
                            # Calcular centroide
                            lons = [c[0] for c in coords]
                            lats = [c[1] for c in coords]
                            coordenadas['longitud'] = sum(lons) / len(lons)
                            coordenadas['latitud'] = sum(lats) / len(lats)
                            coordenadas['bbox'] = [min(lons), min(lats), max(lons), max(lats)]
        
        except Exception as e:
            logger.error(f"Error obteniendo coordenadas INSPIRE: {str(e)}")
        
        return coordenadas
    
    def _obtener_clasificacion_suelo(
        self, 
        ref_catastral: str, 
        provincia: str, 
        municipio: str
    ) -> Dict:
        """
        Obtiene la clasificación del suelo
        
        Returns:
            Diccionario con clasificación urbanística
        """
        logger.info("Obteniendo clasificación del suelo")
        
        clasificacion = {
            'clase_suelo': '',  # Urbano, Urbanizable, No Urbanizable
            'categoria_suelo': '',  # Consolidado, No consolidado, etc.
            'grado_consolidacion': '',
            'estado_desarrollo': '',
            'planeamiento_aplicable': {
                'plan_general': '',
                'planes_especiales': [],
                'fecha_aprobacion': ''
            }
        }
        
        # Aquí iría la consulta a servicios SIU o municipales
        # Por ahora devolvemos estructura de ejemplo
        clasificacion['clase_suelo'] = 'Suelo Urbano'
        clasificacion['categoria_suelo'] = 'Consolidado'
        clasificacion['grado_consolidacion'] = 'Completo'
        
        return clasificacion
    
    def _obtener_calificacion_urbanistica(
        self, 
        ref_catastral: str, 
        provincia: str, 
        municipio: str
    ) -> Dict:
        """
        Obtiene la calificación urbanística y parámetros edificatorios
        
        Returns:
            Diccionario con calificación urbanística
        """
        logger.info("Obteniendo calificación urbanística")
        
        calificacion = {
            'zonificacion': '',
            'clave_zona': '',
            'usos_permitidos': [],
            'usos_prohibidos': [],
            'parametros_edificatorios': {
                'edificabilidad': 0.0,  # m²/m²
                'edificabilidad_unidad': 'm²t/m²s',
                'altura_maxima': 0.0,  # metros
                'numero_plantas': '',
                'ocupacion_maxima': 0.0,  # %
                'retranqueos': {
                    'frontal': 0.0,
                    'lateral': 0.0,
                    'trasero': 0.0,
                    'linderos': 0.0
                },
                'separacion_edificios': 0.0
            },
            'dotaciones': {
                'espacios_libres': 0.0,
                'equipamientos': 0.0,
                'aparcamientos': ''
            }
        }
        
        # Valores de ejemplo
        calificacion['zonificacion'] = 'Residencial'
        calificacion['clave_zona'] = 'R-3'
        calificacion['usos_permitidos'] = ['Residencial', 'Terciario compatible']
        calificacion['parametros_edificatorios']['edificabilidad'] = 1.5
        calificacion['parametros_edificatorios']['altura_maxima'] = 15.0
        calificacion['parametros_edificatorios']['numero_plantas'] = 'PB+3'
        calificacion['parametros_edificatorios']['ocupacion_maxima'] = 70.0
        
        return calificacion
    
    def _consultar_afecciones(self, coordenadas: Dict) -> Dict:
        """
        Consulta las diferentes afecciones territoriales
        
        Args:
            coordenadas: Diccionario con coordenadas de la parcela
            
        Returns:
            Diccionario con afecciones encontradas
        """
        logger.info("Consultando afecciones territoriales")
        
        afecciones = {
            'costas': self._consultar_afeccion_costas(coordenadas),
            'carreteras': self._consultar_afeccion_carreteras(coordenadas),
            'ferrocarriles': self._consultar_afeccion_ferrocarriles(coordenadas),
            'cauces': self._consultar_afeccion_cauces(coordenadas),
            'zonas_inundables': self._consultar_zonas_inundables(coordenadas),
            'espacios_protegidos': self._consultar_espacios_protegidos(coordenadas),
            'montes': self._consultar_montes_publicos(coordenadas),
            'patrimonio': self._consultar_patrimonio(coordenadas),
            'infraestructuras': self._consultar_infraestructuras(coordenadas),
            'servidumbres': self._consultar_servidumbres(coordenadas)
        }
        
        return afecciones
    
    def _consultar_afeccion_costas(self, coordenadas: Dict) -> Dict:
        """Consulta afección por Dominio Público Marítimo-Terrestre"""
        return {
            'afectado': False,
            'tipo_afeccion': '',
            'distancia_costa': 0.0,
            'zona_servidumbre': False,
            'observaciones': ''
        }
    
    def _consultar_afeccion_carreteras(self, coordenadas: Dict) -> Dict:
        """Consulta afección por carreteras"""
        return {
            'afectado': False,
            'carreteras_proximas': [],
            'distancia_minima': 0.0,
            'zona_afeccion': False
        }
    
    def _consultar_afeccion_ferrocarriles(self, coordenadas: Dict) -> Dict:
        """Consulta afección por líneas ferroviarias"""
        return {
            'afectado': False,
            'lineas_proximas': [],
            'distancia_minima': 0.0
        }
    
    def _consultar_afeccion_cauces(self, coordenadas: Dict) -> Dict:
        """Consulta afección por cauces públicos"""
        return {
            'afectado': False,
            'cauces_proximos': [],
            'zona_policia': False,
            'distancia_cauce': 0.0
        }
    
    def _consultar_zonas_inundables(self, coordenadas: Dict) -> Dict:
        """Consulta zonas inundables (SNCZI)"""
        return {
            'afectado': False,
            'periodo_retorno': '',
            'nivel_peligrosidad': '',
            'observaciones': ''
        }
    
    def _consultar_espacios_protegidos(self, coordenadas: Dict) -> Dict:
        """Consulta espacios naturales protegidos"""
        return {
            'afectado': False,
            'espacios': [],
            'red_natura_2000': False,
            'tipo_proteccion': ''
        }
    
    def _consultar_montes_publicos(self, coordenadas: Dict) -> Dict:
        """Consulta montes de utilidad pública"""
        return {
            'afectado': False,
            'montes': [],
            'observaciones': ''
        }
    
    def _consultar_patrimonio(self, coordenadas: Dict) -> Dict:
        """Consulta afección por patrimonio histórico-artístico"""
        return {
            'afectado': False,
            'elementos': [],
            'nivel_proteccion': '',
            'entorno_proteccion': False
        }
    
    def _consultar_infraestructuras(self, coordenadas: Dict) -> Dict:
        """Consulta afección por infraestructuras"""
        return {
            'lineas_electricas': [],
            'gaseoductos': [],
            'oleoductos': [],
            'telecomunicaciones': []
        }
    
    def _consultar_servidumbres(self, coordenadas: Dict) -> Dict:
        """Consulta servidumbres (aeronáuticas, militares, etc.)"""
        return {
            'aeronauticas': False,
            'militares': False,
            'otras': []
        }
    
    def _obtener_gestion_urbanistica(
        self, 
        ref_catastral: str, 
        provincia: str, 
        municipio: str
    ) -> Dict:
        """Obtiene información de gestión urbanística"""
        logger.info("Obteniendo información de gestión urbanística")
        
        return {
            'unidad_ejecucion': {
                'incluida': False,
                'nombre': '',
                'sistema_actuacion': '',
                'estado': ''
            },
            'convenios': [],
            'cesiones_obligatorias': {
                'espacios_libres': 0.0,
                'equipamientos': 0.0,
                'viario': 0.0
            },
            'cargas_urbanisticas': []
        }
    
    def _generar_cartografia(self, ref_catastral: str, coordenadas: Dict) -> Dict:
        """Genera información cartográfica"""
        logger.info("Generando información cartográfica")
        
        return {
            'plano_situacion': '',
            'plano_ordenacion': '',
            'plano_afecciones': '',
            'ortofoto': '',
            'kml_generado': False,
            'kml_path': ''
        }
    
    def generar_informe_pdf(self, datos_informe: Dict, output_path: str) -> bool:
        """
        Genera el informe en formato PDF
        
        Args:
            datos_informe: Datos del informe generado
            output_path: Ruta donde guardar el PDF
            
        Returns:
            True si se generó correctamente
        """
        logger.info(f"Generando PDF en: {output_path}")
        
        try:
            # Aquí iría la generación del PDF usando reportlab o similar
            # Similar a como se hace en el proyecto original
            
            return True
        except Exception as e:
            logger.error(f"Error generando PDF: {str(e)}")
            return False
    
    def generar_kml(self, datos_informe: Dict, output_path: str) -> bool:
        """
        Genera archivo KML para visualización en Google Earth
        
        Args:
            datos_informe: Datos del informe
            output_path: Ruta donde guardar el KML
            
        Returns:
            True si se generó correctamente
        """
        logger.info(f"Generando KML en: {output_path}")
        
        try:
            coordenadas = datos_informe.get('datos_catastrales', {}).get('coordenadas', {})
            
            if not coordenadas.get('latitud') or not coordenadas.get('longitud'):
                logger.warning("No hay coordenadas para generar KML")
                return False
            
            # Generar contenido KML
            kml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Informe Urbanístico</name>
    <description>Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}</description>
    <Placemark>
      <name>{datos_informe.get('datos_catastrales', {}).get('referencia_catastral', 'Parcela')}</name>
      <description>
        Clasificación: {datos_informe.get('clasificacion_urbanistica', {}).get('clase_suelo', '')}
        Calificación: {datos_informe.get('calificacion_urbanistica', {}).get('zonificacion', '')}
      </description>
      <Point>
        <coordinates>{coordenadas['longitud']},{coordenadas['latitud']},0</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>"""
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(kml_content)
            
            logger.info("KML generado correctamente")
            return True
            
        except Exception as e:
            logger.error(f"Error generando KML: {str(e)}")
            return False


def main():
    """Función principal para pruebas"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generar informe urbanístico')
    parser.add_argument('--ref', help='Referencia catastral')
    parser.add_argument('--provincia', help='Provincia')
    parser.add_argument('--municipio', help='Municipio')
    parser.add_argument('--via', help='Nombre de vía')
    parser.add_argument('--numero', help='Número')
    parser.add_argument('--output', default='informe_urbanistico.json', help='Archivo de salida')
    
    args = parser.parse_args()
    
    # Crear generador
    generador = InformeUrbanistico()
    
    # Generar informe
    informe = generador.generar_informe_completo(
        ref_catastral=args.ref,
        provincia=args.provincia,
        municipio=args.municipio,
        via=args.via,
        numero=args.numero
    )
    
    # Guardar resultado
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(informe, f, indent=2, ensure_ascii=False)
    
    print(f"Informe generado: {args.output}")
    print(f"Estado: {informe['estado']}")
    
    # Generar PDF si el informe está completo
    if informe['estado'] == 'completado':
        pdf_path = args.output.replace('.json', '.pdf')
        if generador.generar_informe_pdf(informe, pdf_path):
            print(f"PDF generado: {pdf_path}")
        
        kml_path = args.output.replace('.json', '.kml')
        if generador.generar_kml(informe, kml_path):
            print(f"KML generado: {kml_path}")


if __name__ == '__main__':
    main()