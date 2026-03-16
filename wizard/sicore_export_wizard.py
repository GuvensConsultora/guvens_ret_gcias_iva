# -*- coding: utf-8 -*-
import base64
from datetime import date

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SicoreExportWizard(models.TransientModel):
    """Wizard para exportar retenciones Ganancias en formato SICORE/SIRE.

    Por qué: ARCA requiere dos archivos TXT para declarar retenciones:
    1. "Comprobantes que Generan Beneficio" (Modelo 1) — las retenciones
    2. "Comprobantes que Perfeccionan Derecho a Beneficio" (Modelo 8) — los comprobantes de compra

    Formato: CSV separado por comas, según "Manual para el desarrollador -
    Importación de datos - Diseño de registro" de ARCA.
    """
    _name = 'sicore.export.wizard'
    _description = 'Exportar Retenciones SICORE'

    date_from = fields.Date(
        string='Desde',
        required=True,
        default=lambda self: date.today().replace(day=1),
    )
    date_to = fields.Date(
        string='Hasta',
        required=True,
        default=fields.Date.context_today,
    )
    # Por qué: ARCA pide el período YYYYMM para campos 11 (Periodo DDJJ IVA)
    # y 12 (Periodo Pago) del Modelo 1
    period = fields.Char(
        string='Período (YYYYMM)',
        compute='_compute_period',
        store=True,
    )
    # Por qué: impuesto de Ganancias — filtra retenciones de ese impuesto
    tax_id = fields.Many2one(
        'account.tax',
        string='Impuesto Retención Ganancias',
        domain=[('withholding_type', '=', 'tabla_ganancias')],
        required=True,
    )
    # Código de impuesto ARCA (ej: 0787 para Ganancias)
    cod_impuesto = fields.Char(
        string='Código Impuesto ARCA',
        default='0787',
        help='0787 = Impuesto a las Ganancias',
    )

    # Archivos generados
    file_beneficio = fields.Binary(string='TXT Generan Beneficio', readonly=True)
    file_beneficio_name = fields.Char(default='SICORE_generan_beneficio.txt')
    file_perfeccionan = fields.Binary(string='TXT Perfeccionan Derecho', readonly=True)
    file_perfeccionan_name = fields.Char(default='SICORE_perfeccionan_derecho.txt')
    file_pdf = fields.Binary(string='Reporte PDF', readonly=True)
    file_pdf_name = fields.Char(default='Retenciones_Ganancias.pdf')

    state = fields.Selection([
        ('draft', 'Borrador'),
        ('done', 'Generado'),
    ], default='draft')

    @api.depends('date_from')
    def _compute_period(self):
        for rec in self:
            if rec.date_from:
                rec.period = rec.date_from.strftime('%Y%m')
            else:
                rec.period = ''

    def _get_withholding_payments(self):
        """Busca los pagos de retención del impuesto en el rango de fechas.
        Ruta: account.payment con tax_withholding_id = impuesto seleccionado,
        estado posted, y fecha en rango.
        """
        domain = [
            ('tax_withholding_id', '=', self.tax_id.id),
            ('state', '=', 'posted'),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('payment_type', '=', 'outbound'),
        ]
        payments = self.env['account.payment'].search(domain, order='date asc')
        if not payments:
            raise UserError(_(
                'No se encontraron retenciones de "%s" '
                'entre %s y %s.') % (
                    self.tax_id.name,
                    self.date_from.strftime('%d/%m/%Y'),
                    self.date_to.strftime('%d/%m/%Y')))
        return payments

    def _get_comprobante_tipo(self, move):
        """Mapea move_type de Odoo a código de comprobante SICORE.
        Tabla tipos de comprobantes ARCA:
        1 = Factura A, 6 = Factura B, 3 = Nota de Crédito A, etc.
        """
        if not move:
            # Por qué: anticipo sin factura → usamos código 4 (Recibo A)
            return '04'

        doc_type = move.l10n_latam_document_type_id
        if doc_type:
            code = doc_type.code or ''
            # Mapeo por código de documento AFIP
            mapping = {
                '1': '01',    # Factura A
                '2': '02',    # Nota de Débito A
                '3': '03',    # Nota de Crédito A
                '6': '06',    # Factura B
                '7': '07',    # Nota de Débito B
                '8': '08',    # Nota de Crédito B
                '11': '51',   # Factura M
                '12': '52',   # Nota de Débito M
                '13': '53',   # Nota de Crédito M
                '51': '51',   # Factura M
                '201': '201', # FCE A
                '206': '206', # FCE B
            }
            return mapping.get(code, code.zfill(2) if code else '01')
        return '01'

    def _get_invoices_for_payment(self, payment):
        """Obtiene facturas asociadas al payment_group del pago de retención.
        Por qué: el Modelo 8 (perfeccionan derecho) necesita los comprobantes
        de compra que originaron la retención.
        """
        if not payment.payment_group_id:
            return self.env['account.move']
        moves = payment.payment_group_id.matched_move_line_ids.mapped('move_id')
        return moves.filtered(
            lambda m: m.move_type in ('in_invoice', 'in_refund')
        )

    def _format_amount(self, amount, integer_digits=13, decimal_digits=2):
        """Formatea monto: enteros.decimales con punto.
        Ej: 1500.00 → '1500.00', longitud variable.
        Por qué: ARCA usa longitud máxima (13.2*) pero acepta
        valores más cortos en CSV.
        """
        if amount < 0:
            amount = abs(amount)
        fmt = f'{amount:.{decimal_digits}f}'
        return fmt

    def _format_cuit(self, vat):
        """Limpia CUIT: solo números, 11 dígitos.
        Por qué: campo 5 del Modelo 1 es numérico, 11 chars.
        """
        if not vat:
            return '00000000000'
        clean = ''.join(c for c in vat if c.isdigit())
        return clean.ljust(11, '0')[:11]

    def _get_sign(self, move):
        """Signo del comprobante: + para facturas/débito, - para créditos.
        Por qué: campo 10 del Modelo 1.
        """
        if move and move.move_type == 'in_refund':
            return '-'
        return '+'

    def _get_regimen_code(self, payment):
        """Código de régimen de retención para el campo 21 del Modelo 1.
        Por qué: ARCA necesita el código numérico del régimen (ej: 94, 116).
        """
        pg = payment.payment_group_id
        if pg and pg.regimen_ganancias_id:
            return pg.regimen_ganancias_id.codigo_de_regimen or ''
        return ''

    def _build_generan_beneficio(self, payments):
        """Genera TXT de 'Comprobantes que Generan Beneficio' - Modelo 1.

        Diseño de registro (21 campos, separados por coma):
        1.  Tipo de Comprobante (10, numérico) → tabla comprobantes
        2.  Punto de venta (5*, numérico)
        3.  Nro. Comprobante (8*, numérico)
        4.  CUIT Emisor (11, numérico)
        5.  CUIT Vendedor (11, numérico) → CUIT del sujeto retenido
        6.  Descripción Bien (100*, alfanumérico)
        7.  Importe IVA Facturado (13.2*, numérico)
        8.  Importe Neto (13.2*, numérico)
        9.  Importe IVA Computable (13.2*, numérico)
        10. Signo Comprobante (1, alfanumérico) → + o -
        11. Periodo DDJJ IVA (6, numérico) → YYYYMM
        12. Periodo Pago (6, numérico) → YYYYMM
        13. Medio Pago (numérico) → tabla medios de pago
        14. Crédito Fiscal (1, alfanumérico) → D (Directa) o I (Indirecta)
        15. Nro. Certificado Sire (numérico)
        16. Nro. Certificado Sicore (numérico)
        17. Agente de retención de IVA (1, alfanumérico) → S o N
        18. Monto IVA Retenido (13.2*, numérico)
        19. Motivo no retención (numérico) → tabla motivos
        20. Fecha comprobante (10, alfanumérico) → DD/MM/AAAA
        21. Código de régimen de retención (numérico) → tabla regímenes
        """
        lines = []
        for payment in payments:
            pg = payment.payment_group_id
            partner = pg.commercial_partner_id if pg else payment.partner_id
            cuit_retenido = self._format_cuit(partner.vat)

            # CUIT del agente de retención (nuestra empresa)
            company = payment.company_id
            cuit_emisor = self._format_cuit(company.vat)

            # Comprobante: usamos Recibo (código 04 = Recibo A) para la retención
            # El nro viene del withholding_number o payment name
            wh_number = payment.withholding_number or payment.name or ''
            # Extraer punto de venta y número del comprobante
            punto_venta, nro_comp = self._parse_comprobante_number(wh_number)

            # Facturas asociadas para calcular IVA
            invoices = self._get_invoices_for_payment(payment)
            iva_facturado = sum(
                inv.amount_tax for inv in invoices
                if inv.move_type == 'in_invoice'
            )
            importe_neto = sum(
                inv.amount_untaxed for inv in invoices
                if inv.move_type == 'in_invoice'
            )
            # Por qué: para retenciones Ganancias, el IVA computable
            # generalmente es 0 (no genera crédito fiscal)
            iva_computable = 0.0

            # Signo: + para operaciones normales
            signo = '+'

            # Período
            period = self.period

            # Medio de pago: 6 = Efectivo (default para retenciones)
            medio_pago = '6'

            # Crédito fiscal: D = Directa
            credito_fiscal = 'D'

            # Nro certificado SIRE/SICORE
            nro_cert_sire = ''
            nro_cert_sicore = ''

            # Agente de retención de IVA: N (este es Ganancias, no IVA)
            agente_ret_iva = 'N'

            # Monto retenido
            monto_retenido = self._format_amount(payment.amount)

            # Motivo no retención: 0 (sin motivo, porque sí retuvimos)
            motivo_no_ret = '0'

            # Fecha comprobante
            fecha = payment.date.strftime('%d/%m/%Y') if payment.date else ''

            # Código de régimen
            cod_regimen = self._get_regimen_code(payment)

            # Descripción del bien/servicio
            descripcion = 'RETENCION GANANCIAS'

            # Armar línea CSV (21 campos)
            line = ','.join([
                '04',                                    # 1. Tipo comprobante (Recibo A)
                punto_venta,                             # 2. Punto de venta
                nro_comp,                                # 3. Nro comprobante
                cuit_emisor,                             # 4. CUIT Emisor
                cuit_retenido,                           # 5. CUIT Vendedor (retenido)
                descripcion,                             # 6. Descripción Bien
                self._format_amount(iva_facturado),      # 7. Importe IVA Facturado
                self._format_amount(importe_neto),       # 8. Importe Neto
                self._format_amount(iva_computable),     # 9. Importe IVA Computable
                signo,                                   # 10. Signo
                period,                                  # 11. Periodo DDJJ IVA
                period,                                  # 12. Periodo Pago
                medio_pago,                              # 13. Medio Pago
                credito_fiscal,                          # 14. Crédito Fiscal
                nro_cert_sire,                           # 15. Nro Certificado Sire
                nro_cert_sicore,                         # 16. Nro Certificado Sicore
                agente_ret_iva,                          # 17. Agente ret IVA
                monto_retenido,                          # 18. Monto IVA Retenido
                motivo_no_ret,                           # 19. Motivo no retención
                fecha,                                   # 20. Fecha comprobante
                cod_regimen,                             # 21. Código régimen retención
            ])
            lines.append(line)

        return '\r\n'.join(lines)

    def _build_perfeccionan_derecho(self, payments):
        """Genera TXT de 'Comprobantes que Perfeccionan Derecho a Beneficio' - Modelo 8.

        Diseño de registro (17 campos, separados por coma):
        1.  Tipo de Comprobante (10, numérico)
        2.  Punto de venta (5, numérico)
        3.  Nro. Comprobante (8*, numérico)
        4.  Fecha Comprobante (10, alfanumérico) → DD/MM/AAAA
        5.  CUIT Cliente (11, numérico) → CUIT del sujeto retenido
        6.  Precio Total (13.2*, numérico)
        7.  Tipo Transporte (numérico) → tabla transporte (vacío si no aplica)
        8.  Nombre Buque (30*, alfanumérico)
        9.  Número Vuelo (10*, alfanumérico)
        10. Número Viaje (10*, alfanumérico)
        11. Nombre Cía. Transporte (30*, alfanumérico)
        12. Tipo Documento Exportación (1, numérico)
        13. Nro. Doc. Exportación (16*, numérico)
        14. Nro. Permiso Embarque (16, alfanumérico)
        15. Punto Venta Exp. (5*, numérico)
        16. Nro. Comprobante Exp. (8*, numérico)
        17. Fecha Perfeccionamiento (10, alfanumérico) → DD/MM/AAAA
        """
        lines = []
        for payment in payments:
            invoices = self._get_invoices_for_payment(payment)
            pg = payment.payment_group_id
            partner = pg.commercial_partner_id if pg else payment.partner_id
            cuit = self._format_cuit(partner.vat)

            if not invoices:
                # Por qué: anticipo sin factura → generar línea con recibo
                fecha = payment.date.strftime('%d/%m/%Y') if payment.date else ''
                line = ','.join([
                    '04',                                    # 1. Tipo (Recibo A)
                    '00000',                                 # 2. Punto venta
                    '00000000',                              # 3. Nro comprobante
                    fecha,                                   # 4. Fecha
                    cuit,                                    # 5. CUIT
                    self._format_amount(payment.amount),     # 6. Precio Total
                    '',                                      # 7. Tipo transporte
                    '',                                      # 8. Nombre buque
                    '',                                      # 9. Nro vuelo
                    '',                                      # 10. Nro viaje
                    '',                                      # 11. Cía transporte
                    '',                                      # 12. Tipo doc exportación
                    '',                                      # 13. Nro doc exportación
                    '',                                      # 14. Nro permiso embarque
                    '',                                      # 15. Punto venta exp
                    '',                                      # 16. Nro comprobante exp
                    fecha,                                   # 17. Fecha perfeccionamiento
                ])
                lines.append(line)
                continue

            for inv in invoices:
                tipo_comp = self._get_comprobante_tipo(inv)
                inv_name = inv.name or ''
                punto_venta, nro_comp = self._parse_comprobante_number(inv_name)
                fecha = inv.invoice_date.strftime('%d/%m/%Y') if inv.invoice_date else ''
                precio_total = self._format_amount(inv.amount_total)
                signo = self._get_sign(inv)

                # Para NC, el precio es negativo en SICORE
                if inv.move_type == 'in_refund':
                    precio_total = self._format_amount(-abs(inv.amount_total))

                line = ','.join([
                    tipo_comp,          # 1. Tipo comprobante
                    punto_venta,        # 2. Punto venta
                    nro_comp,           # 3. Nro comprobante
                    fecha,              # 4. Fecha comprobante
                    cuit,               # 5. CUIT
                    precio_total,       # 6. Precio Total
                    '',                 # 7. Tipo transporte
                    '',                 # 8. Nombre buque
                    '',                 # 9. Nro vuelo
                    '',                 # 10. Nro viaje
                    '',                 # 11. Cía transporte
                    '',                 # 12. Tipo doc exportación
                    '',                 # 13. Nro doc exportación
                    '',                 # 14. Nro permiso embarque
                    '',                 # 15. Punto venta exp
                    '',                 # 16. Nro comprobante exp
                    fecha,              # 17. Fecha perfeccionamiento
                ])
                lines.append(line)

        return '\r\n'.join(lines)

    def _parse_comprobante_number(self, name):
        """Extrae punto de venta y número de un comprobante Odoo.
        Ej: 'FA-A 0001-00000020' → ('00001', '00000020')
        Ej: 'RET/2024/001' → ('00000', '00000001')
        """
        if not name:
            return '00000', '00000000'

        # Buscar patrón XXXX-XXXXXXXX
        parts = name.split()
        for part in parts:
            if '-' in part:
                segments = part.split('-')
                if len(segments) >= 2:
                    try:
                        pv = segments[-2].strip()
                        nc = segments[-1].strip()
                        # Verificar que sean numéricos
                        if pv.isdigit() and nc.isdigit():
                            return pv.zfill(5), nc.zfill(8)
                    except (ValueError, IndexError):
                        pass

        # Fallback: intentar extraer números
        import re
        nums = re.findall(r'\d+', name)
        if len(nums) >= 2:
            return nums[-2].zfill(5), nums[-1].zfill(8)
        elif len(nums) == 1:
            return '00000', nums[0].zfill(8)

        return '00000', '00000000'

    def _build_pdf_data(self, payments):
        """Prepara datos para el reporte PDF de retenciones.
        Por qué: el usuario necesita un resumen imprimible con todos
        los datos que se incluyen en los TXT.
        """
        data = []
        total_retenido = 0.0
        for payment in payments:
            pg = payment.payment_group_id
            partner = pg.commercial_partner_id if pg else payment.partner_id
            invoices = self._get_invoices_for_payment(payment)

            regimen = ''
            if pg and pg.regimen_ganancias_id:
                regimen = '%s - %s' % (
                    pg.regimen_ganancias_id.codigo_de_regimen or '',
                    pg.regimen_ganancias_id.concepto_referencia or '',
                )

            data.append({
                'date': payment.date,
                'partner': partner.name,
                'cuit': partner.vat or '',
                'withholding_number': payment.withholding_number or payment.name or '',
                'amount': payment.amount,
                'regimen': regimen,
                'invoices': [{
                    'name': inv.name or '',
                    'date': inv.invoice_date,
                    'total': inv.amount_total,
                    'untaxed': inv.amount_untaxed,
                } for inv in invoices],
            })
            total_retenido += payment.amount

        return data, total_retenido

    def action_generate(self):
        """Genera los dos archivos TXT + reporte PDF."""
        self.ensure_one()

        if self.date_from > self.date_to:
            raise UserError(_('La fecha "Desde" debe ser anterior a "Hasta".'))

        payments = self._get_withholding_payments()

        # 1. TXT Generan Beneficio (Modelo 1)
        txt_beneficio = self._build_generan_beneficio(payments)
        self.file_beneficio = base64.b64encode(
            txt_beneficio.encode('utf-8'))
        self.file_beneficio_name = 'SICORE_generan_beneficio_%s.txt' % self.period

        # 2. TXT Perfeccionan Derecho (Modelo 8)
        txt_perfeccionan = self._build_perfeccionan_derecho(payments)
        self.file_perfeccionan = base64.b64encode(
            txt_perfeccionan.encode('utf-8'))
        self.file_perfeccionan_name = 'SICORE_perfeccionan_derecho_%s.txt' % self.period

        # 3. PDF (QWeb report — lee datos directamente del wizard via docs)
        report = self.env.ref(
            'guvens_ret_gcias_iva.action_report_sicore_retenciones')
        pdf_content, _ = report._render_qweb_pdf(
            report.report_name, res_ids=self.ids)
        self.file_pdf = base64.b64encode(pdf_content)
        self.file_pdf_name = 'Retenciones_Ganancias_%s.pdf' % self.period

        self.state = 'done'

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
