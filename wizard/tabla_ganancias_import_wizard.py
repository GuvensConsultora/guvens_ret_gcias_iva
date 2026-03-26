# -*- coding: utf-8 -*-
import io
import re
import requests

from odoo import models, fields, _
from odoo.exceptions import UserError

MESES = [
    ('1', 'Enero'), ('2', 'Febrero'), ('3', 'Marzo'),
    ('4', 'Abril'), ('5', 'Mayo'), ('6', 'Junio'),
    ('7', 'Julio'), ('8', 'Agosto'), ('9', 'Septiembre'),
    ('10', 'Octubre'), ('11', 'Noviembre'), ('12', 'Diciembre'),
]

MONTH_LABELS = {
    '1': 'ENERO', '2': 'FEBRERO', '3': 'MARZO',
    '4': 'ABRIL', '5': 'MAYO', '6': 'JUNIO',
    '7': 'JULIO', '8': 'AGOSTO', '9': 'SEPTIEMBRE',
    '10': 'OCTUBRE', '11': 'NOVIEMBRE', '12': 'DICIEMBRE',
}

DEFAULT_URL_ESCALA = (
    'https://www.afip.gob.ar/gananciasYBienes/ganancias/'
    'personas-humanas-sucesiones-indivisas/declaracion-jurada/'
    'documentos/Tabla-Art-94-LIG-per-ene-a-jun-2026.pdf'
)
DEFAULT_URL_REGIMENES = (
    'https://biblioteca.afip.gob.ar/search/query/adjunto.aspx'
    '?p=t:RAG%7Cn:830%7Co:3%7Ca:2000%7Cd:A8_RG5423.pdf'
)


class TablaGananciasImportWizard(models.TransientModel):
    _name = 'tabla.ganancias.import.wizard'
    _description = 'Actualizar tablas de Ganancias desde ARCA'

    mes = fields.Selection(MESES, string='Mes de pago', required=True,
                           default=lambda self: str(fields.Date.today().month))
    url_escala = fields.Char('URL Escala Art. 94', default=DEFAULT_URL_ESCALA)
    url_regimenes = fields.Char('URL Anexo VIII RG 830', default=DEFAULT_URL_REGIMENES)
    resultado = fields.Text('Resultado', readonly=True)

    # ── Escala ──────────────────────────────────────────────────

    def action_actualizar_escala(self):
        self.ensure_one()
        pdf_bytes = self._fetch_pdf(self.url_escala, 'Escala Art. 94')
        rows = self._parse_escala(pdf_bytes, MONTH_LABELS[self.mes])

        Escala = self.env['afip.tabla_ganancias.escala']
        Escala.search([]).unlink()
        Escala.create(rows)

        msg = 'Escala %s: %d tramos cargados desde ARCA.' % (
            MONTH_LABELS[self.mes].capitalize(), len(rows))
        self.resultado = msg
        return self._notify(msg)

    # ── Regímenes ───────────────────────────────────────────────

    def action_actualizar_regimenes(self):
        self.ensure_one()
        pdf_bytes = self._fetch_pdf(self.url_regimenes, 'Anexo VIII RG 830')
        rows = self._parse_regimenes(pdf_bytes)

        Alicuotas = self.env['afip.tabla_ganancias.alicuotasymontos']
        Alicuotas.search([]).unlink()
        Alicuotas.create(rows)

        msg = 'Regímenes: %d cargados desde ARCA.' % len(rows)
        self.resultado = msg
        return self._notify(msg)

    # ── Helpers ─────────────────────────────────────────────────

    def _fetch_pdf(self, url, label):
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            raise UserError(_(
                'No se pudo descargar %s.\nURL: %s\nError: %s') % (
                label, url, e))
        if not resp.content[:5] == b'%PDF-':
            raise UserError(_(
                'La URL no devolvió un PDF válido.\nURL: %s') % url)
        return resp.content

    def _parse_escala(self, pdf_bytes, mes_label):
        """Extrae los 9 tramos del mes indicado del PDF Art. 94."""
        try:
            import pdfplumber
        except ImportError:
            raise UserError(_(
                'Se requiere la librería pdfplumber.\n'
                'Instalar: pip install pdfplumber'))

        rows = []
        found = False
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables():
                    for raw_row in table:
                        # Limpiar Nones
                        cells = [c for c in raw_row if c is not None]
                        if not cells:
                            continue
                        # Detectar inicio del mes buscado
                        first = cells[0].strip().replace('\n', ' ')
                        if first.upper() == mes_label:
                            found = True
                            data_cells = cells[1:]
                        elif found and first.upper() in MONTH_LABELS.values():
                            # Llegamos al mes siguiente
                            break
                        elif found and len(cells) >= 5:
                            data_cells = cells
                        else:
                            continue

                        if found and len(data_cells) >= 5:
                            vals = self._parse_escala_row(data_cells)
                            if vals:
                                rows.append(vals)

        if not rows:
            raise UserError(_(
                'No se encontró el mes %s en el PDF.') % mes_label)
        return rows

    def _parse_escala_row(self, cells):
        """Convierte una fila de texto PDF a dict de escala."""
        try:
            desde = self._parse_num(cells[0])
            hasta_raw = cells[1].strip()
            if 'adelante' in hasta_raw.lower():
                hasta = 99999999999.0
            else:
                hasta = self._parse_num(cells[1])
            fijo = self._parse_num(cells[2])
            porcentaje = float(cells[3].strip().replace('%', '').replace(',', '.'))
            excedente = self._parse_num(cells[4])
            return {
                'importe_desde': desde,
                'importe_hasta': hasta,
                'importe_fijo': fijo,
                'porcentaje': porcentaje,
                'importe_excedente': excedente,
            }
        except (ValueError, IndexError):
            return None

    def _parse_regimenes(self, pdf_bytes):
        """Extrae regímenes del Anexo VIII RG 830."""
        try:
            import pdfplumber
        except ImportError:
            raise UserError(_(
                'Se requiere la librería pdfplumber.\n'
                'Instalar: pip install pdfplumber'))

        rows = []
        # Valores "carry" para celdas merged (None)
        last_pct_insc = None
        last_pct_no_insc = None
        last_monto = None

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages[:-1]:  # Última página es la escala, no regímenes
                for table in page.extract_tables():
                    for raw_row in table:
                        codigo = (raw_row[0] or '').strip()
                        # Saltar headers, notas y filas vacías
                        if not codigo or codigo.startswith('(') or \
                           'CÓDIGO' in codigo.upper() or not codigo[0].isdigit():
                            continue

                        # Concepto: columnas 1 y 2 (referencia + descripción)
                        anexo = (raw_row[1] or '').strip().replace('\n', ' ')
                        concepto = (raw_row[2] or '').strip().replace('\n', ' ')

                        # % inscripto
                        pct_insc_raw = raw_row[3] if len(raw_row) > 3 else None
                        if pct_insc_raw:
                            last_pct_insc = self._parse_pct_inscripto(pct_insc_raw)
                        pct_insc = last_pct_insc or 0

                        # % no inscripto
                        pct_no_insc_raw = raw_row[4] if len(raw_row) > 4 else None
                        if pct_no_insc_raw:
                            last_pct_no_insc = self._parse_pct_no_inscripto(
                                pct_no_insc_raw)
                        pct_no_insc = last_pct_no_insc or 0

                        # Monto no sujeto
                        monto_raw = raw_row[5] if len(raw_row) > 5 else None
                        if monto_raw:
                            last_monto = self._parse_monto(monto_raw)
                        monto = last_monto or 0

                        rows.append({
                            'codigo_de_regimen': codigo,
                            'anexo_referencia': anexo,
                            'concepto_referencia': concepto,
                            'porcentaje_inscripto': pct_insc,
                            'porcentaje_no_inscripto': pct_no_insc,
                            'montos_no_sujetos_a_retencion': monto,
                        })

        if not rows:
            raise UserError(_('No se encontraron regímenes en el PDF.'))

        # Desambiguar códigos duplicados (ej: 116 → 116 I, 116 II)
        seen = {}
        for row in rows:
            cod = row['codigo_de_regimen']
            seen[cod] = seen.get(cod, 0) + 1
        duplicates = {k for k, v in seen.items() if v > 1}
        counters = {}
        if duplicates:
            romanos = {1: 'I', 2: 'II', 3: 'III', 4: 'IV'}
            for row in rows:
                cod = row['codigo_de_regimen']
                if cod in duplicates:
                    counters[cod] = counters.get(cod, 0) + 1
                    row['codigo_de_regimen'] = '%s %s' % (
                        cod, romanos.get(counters[cod], str(counters[cod])))

        return rows

    def _parse_pct_inscripto(self, raw):
        """'3%' → 3.0, 's/escala' → -1, None/vacío → None"""
        raw = raw.strip()
        if 'escala' in raw.lower():
            return -1.0
        raw = raw.replace('%', '').replace(',', '.').strip()
        try:
            return float(raw)
        except ValueError:
            return None

    def _parse_pct_no_inscripto(self, raw):
        """'25%/28%(e)' → 28.0, '10%' → 10.0"""
        raw = raw.strip().replace('\n', '')
        # Si hay formato "X%/Y%(e)", tomar el segundo (mayor)
        match = re.search(r'(\d+(?:[.,]\d+)?)\s*%\s*\(', raw)
        if match:
            return float(match.group(1).replace(',', '.'))
        # Último porcentaje encontrado
        matches = re.findall(r'(\d+(?:[.,]\d+)?)\s*%', raw)
        if matches:
            return float(matches[-1].replace(',', '.'))
        return None

    def _parse_monto(self, raw):
        """'67,170' → 67170.0, '160.000' → 160000.0, '- .-' → 0"""
        raw = raw.strip()
        # Limpiar notas tipo "(b)"
        raw = re.sub(r'\([^)]*\)', '', raw).strip()
        if not raw or raw == '- .-' or raw == '-':
            return 0.0
        # En el PDF de ARCA los montos usan punto o coma como separador
        # de miles (no decimales): "67,170" = 67170, "160.000" = 160000
        cleaned = raw.replace('.', '').replace(',', '')
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    def _parse_num(self, raw):
        """Convierte número del PDF: '1.500.022,56' → 1500022.56"""
        raw = raw.strip()
        if not raw or raw == '-' or raw == '--':
            return 0.0
        # Formato argentino: punto = miles, coma = decimal
        raw = raw.replace('.', '').replace(',', '.')
        return float(raw)

    def _notify(self, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Tablas de Ganancias'),
                'message': message,
                'type': 'success',
                'sticky': False,
            },
        }
