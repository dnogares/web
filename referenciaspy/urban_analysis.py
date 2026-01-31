import os
from pathlib import Path
from datetime import datetime
import logging
import geopandas as gpd
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image

logger = logging.getLogger(__name__)

class AnalizadorUrbanistico:
    def __init__(self, outputs_dir: str = "/app/outputs"):
        self.outputs_dir = Path(outputs_dir)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)

    def generar_informe_pdf(self, datos_parcela, afecciones, referencia):
        file_name = f"Informe_{referencia}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        file_path = self.outputs_dir / file_name
        
        doc = SimpleDocTemplate(str(file_path), pagesize=A4)
        styles = getSampleStyleSheet()
        elements = []

        # TÃ­tulo
        elements.append(Paragraph(f"INFORME TÃ‰CNICO DE AFECCIONES", styles['Title']))
        elements.append(Paragraph(f"Referencia Catastral: {referencia}", styles['Heading2']))
        elements.append(Spacer(1, 12))

        # Cuadro de Datos BÃ¡sicos
        data = [
            ["Fecha de AnÃ¡lisis", datetime.now().strftime("%d/%m/%Y")],
            ["LocalizaciÃ³n", datos_parcela.get('nm', 'Consultar Sede')],
            ["Superficie Catastral", f"{datos_parcela.get('area', 'N/A')} mÂ²"]
        ]
        t = Table(data, colWidths=[150, 300])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (0,-1), colors.lightgrey),
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
            ('PADDING', (0,0), (-1,-1), 6),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 20))

        # SecciÃ³n de Afecciones (Usando tus Leyendas CSV)
        elements.append(Paragraph("ANÃLISIS DE AFECCIONES AMBIENTALES", styles['Heading3']))
        
        if not afecciones:
            elements.append(Paragraph("No se han detectado afecciones en las capas analizadas.", styles['Normal']))
        else:
            for af in afecciones:
                # Extraemos el color de tu CSV (ej: #33A02C)
                color_hex = af['leyenda'][0]['color'] if af['leyenda'] else "#3b82f6"
                desc = af['leyenda'][0]['etiqueta'] if af['leyenda'] else "Zona Protegida"
                
                # Crear una pequeÃ±a tabla para cada afecciÃ³n con su color
                af_data = [[f"CAPA: {af['capa']}", f"TIPO: {desc}"]]
                af_table = Table(af_data, colWidths=[200, 250])
                af_table.setStyle(TableStyle([
                    ('BORDERLEFT', (0,0), (0,0), 10, colors.HexColor(color_hex)),
                    ('BACKGROUND', (0,0), (-1,-1), colors.whitesmoke),
                    ('PADDING', (0,0), (-1,-1), 8),
                ]))
                elements.append(af_table)
                elements.append(Spacer(1, 8))

        # Pie de pÃ¡gina
        elements.append(Spacer(1, 40))
        elements.append(Paragraph("Este informe es meramente informativo y basado en los datos disponibles en el volumen local.", styles['Italic']))

        doc.build(elements)
        return file_name
