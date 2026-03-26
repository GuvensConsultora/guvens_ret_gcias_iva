# -*- coding: utf-8 -*-
import base64
from datetime import date

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SicoreExportWizard(models.TransientModel):
    """Wizard para exportar retenciones Ganancias en formato SICORE Estándar.

    Por qué: ARCA requiere un TXT de posición fija ("Estándar Retenciones Versión 3.0")
    para importar retenciones en el aplicativo SICORE.
    Formato: 198 chars por registro, sin separadores entre campos.
    Un registro por factura asociada al pago (base e importe prorrateados).
    Ref: Manual SICORE - Diseño de registro (21 campos, 198 posiciones fijas).
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
    # Por qué: SICORE no usa el período directamente en el registro,
    # pero sí para nombrar el archivo generado
    period = fields.Char(
        string='Período (YYYYMM)',
        compute='_compute_period',
        store=True,
    )
    tax_id = fields.Many2one(
        'account.tax',
        string='Impuesto Retención Ganancias',
        domain=[('withholding_type', '=', 'tabla_ganancias')],
        required=True,
    )
    # Código ARCA del impuesto (3 dígitos):
    # 217 = Ganancias general  |  787 = Ganancias Relación de Dependencia
    cod_impuesto = fields.Char(
        string='Código Impuesto ARCA',
        default='217',
        help='217 = Impuesto a las Ganancias (general)\n'
             '787 = Ganancias - Relación de Dependencia',
    )

    file_txt = fields.Binary(string='TXT SICORE', readonly=True)
    file_txt_name = fields.Char(default='SICORE_retenciones.txt')
    file_pdf = fields.Binary(string='Reporte PDF', readonly=True)
    file_pdf_name = fields.Char(default='Retenciones_Ganancias.pdf')

    state = fields.Selection([
        ('draft', 'Borrador'),
        ('done', 'Generado'),
    ], default='draft')

    @api.depends('date_from')
    def _compute_period(self):
        for rec in self:
            rec.period = rec.date_from.strftime('%Y%m') if rec.date_from else ''

    # ── Búsqueda ──────────────────────────────────────────────────────────────

    def _get_withholding_payments(self):
        """Retorna los pagos de retención del impuesto en el rango de fechas."""
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
                'No se encontraron retenciones de "%s" entre %s y %s.') % (
                    self.tax_id.name,
                    self.date_from.strftime('%d/%m/%Y'),
                    self.date_to.strftime('%d/%m/%Y')))
        return payments

    def _get_invoices_for_payment(self, payment):
        """Facturas de compra asociadas al payment_group del pago."""
        if not payment.payment_group_id:
            return self.env['account.move']
        moves = payment.payment_group_id.matched_move_line_ids.mapped('move_id')
        return moves.filtered(
            lambda m: m.move_type in ('in_invoice', 'in_refund')
        )

    # ── Helpers de formato SICORE (posición fija) ─────────────────────────────

    def _fmt_num16(self, amount):
        """Numérico 16 chars: 13 enteros + ',' + 2 decimales.
        Por qué: campo 4 (importe comprobante). Separador decimal = coma (SICORE).
        Ej: 1500.75 → '0000000001500,75'
        """
        amount = abs(float(amount or 0))
        enteros = int(amount)
        # Por qué: round() evita errores de punto flotante en los centavos
        centavos = round((amount - enteros) * 100)
        return str(enteros).zfill(13) + ',' + str(centavos).zfill(2)

    def _fmt_num14(self, amount):
        """Numérico 14 chars: 11 enteros + ',' + 2 decimales.
        Por qué: campos 8 (base cálculo) y 12 (importe retención).
        Ej: 1500.75 → '00000001500,75'
        """
        amount = abs(float(amount or 0))
        enteros = int(amount)
        centavos = round((amount - enteros) * 100)
        return str(enteros).zfill(11) + ',' + str(centavos).zfill(2)

    def _fmt_cuit(self, vat):
        """CUIT limpio: solo dígitos, 11 chars, zfill.
        Por qué: campos 16 y 21 son numéricos sin guiones ni espacios.
        """
        if not vat:
            return '00000000000'
        clean = ''.join(c for c in vat if c.isdigit())
        return clean.zfill(11)[:11]

    def _get_cod_comprobante(self, inv):
        """Mapea tipo de comprobante AFIP al código SICORE de 2 chars.
        Por qué: campo 1 — tabla tipos de comprobante SICORE.
        01=Factura, 02=Recibo, 03=Nota de Crédito, 04=Nota de Débito.
        """
        if not inv:
            # Anticipo sin factura → Recibo
            return '02'
        # NC de proveedor → código 03
        if inv.move_type == 'in_refund':
            return '03'
        doc_type = inv.l10n_latam_document_type_id
        if not doc_type:
            return '01'
        mapping = {
            '1': '01', '6': '01', '11': '01',   # Facturas A, B, M
            '51': '01', '201': '01', '206': '01', '211': '01',  # FCE
            '2': '04', '7': '04', '12': '04',    # Notas de Débito
            '3': '03', '8': '03', '13': '03',    # Notas de Crédito
        }
        return mapping.get(str(doc_type.code or '1'), '01')

    def _get_cod_condicion(self, partner):
        """Código de condición SICORE desde imp_ganancias_padron del partner.
        Por qué: campo 10 — indica la situación fiscal del retenido ante AFIP.
        01=Inscripto, 02=No inscripto, 04=Exento, 05=No alcanzado.
        """
        padron = getattr(partner, 'imp_ganancias_padron', '') or ''
        return {
            'AC': '01',
            'NI': '02',
            'EX': '04',
            'NA': '05',
        }.get(padron, '01')

    # ── Constructor de registro ────────────────────────────────────────────────

    def _build_record(self, payment, inv, base_inv, ret_inv):
        """Construye un registro SICORE de exactamente 198 chars.

        Por qué: el formato "Estándar Retenciones" exige posición fija
        sin separadores. Cada campo tiene longitud y alineación definida.
        Patrón: mismo principio que ARBA A-122R pero con 21 campos y 198 chars.

        Args:
            payment : account.payment — el pago de retención
            inv     : account.move | False — factura asociada (False = anticipo)
            base_inv: float — base de cálculo prorrateada para esta factura
            ret_inv : float — importe retención prorrateado para esta factura
        """
        pg = payment.payment_group_id
        partner = pg.commercial_partner_id if pg else payment.partner_id
        company = payment.company_id

        # 1. Código comprobante (2, num)
        f1 = self._get_cod_comprobante(inv)

        # 2. Fecha emisión comprobante (10, alfa DD/MM/AAAA)
        f2 = (inv.invoice_date if inv else payment.date).strftime('%d/%m/%Y')

        # 3. Número comprobante (16, alfa, ljust + espacios)
        # Por qué: nombre del comprobante AFIP tal como está en Odoo (ej: "FA-A 0001-00000020")
        nombre_comp = (inv.name if inv else payment.withholding_number or payment.name) or ''
        f3 = nombre_comp.strip()[:16].ljust(16)

        # 4. Importe comprobante (16, num 13ent+coma+2dec)
        f4 = self._fmt_num16(inv.amount_total if inv else payment.amount)

        # 5. Código impuesto (3, num, zfill)
        f5 = (self.cod_impuesto or '217').strip().zfill(3)[:3]

        # 6. Código régimen (4, num, zfill)
        # Por qué: identifica el régimen de retención Ganancias en ARCA
        regimen_code = ''
        if pg and pg.regimen_ganancias_id:
            regimen_code = pg.regimen_ganancias_id.codigo_de_regimen or ''
        f6 = regimen_code.strip().zfill(4)[:4] if regimen_code else '0000'

        # 7. Código operación (1) → 1=Retención (siempre)
        f7 = '1'

        # 8. Base de cálculo (14, num 11ent+coma+2dec)
        f8 = self._fmt_num14(base_inv)

        # 9. Fecha emisión retención (10, alfa DD/MM/AAAA)
        f9 = payment.date.strftime('%d/%m/%Y')

        # 10. Código condición (2, num)
        f10 = self._get_cod_condicion(partner)

        # 11. Retención a sujeto suspendido (1) → 0=No (siempre para Ganancias)
        f11 = '0'

        # 12. Importe retención (14, num 11ent+coma+2dec)
        f12 = self._fmt_num14(ret_inv)

        # 13. Porcentaje exclusión (6) → sin exclusión
        f13 = '000,00'

        # 14. Fecha boletín oficial (10, alfa) → no aplica → espacios
        f14 = ' ' * 10

        # 15. Tipo documento retenido (2, num) → 80=CUIT
        f15 = '80'

        # 16. Nro. documento retenido (20, alfa, ljust+espacios)
        # Por qué: 11 dígitos CUIT + 9 espacios para completar los 20 chars
        f16 = self._fmt_cuit(partner.vat).ljust(20)

        # 17. Nro. certificado original (14, num) → ceros (solo para anulaciones)
        f17 = '0' * 14

        # 18. Denominación ordenante/pagador (30, alfa, ljust+espacios)
        f18 = (company.name or '')[:30].ljust(30)

        # 19. Acrecentamiento (1) → 0=No (no aplica a beneficiarios locales)
        f19 = '0'

        # 20. CUIT país del retenido exterior (11, num) → ceros (beneficiarios locales)
        f20 = '0' * 11

        # 21. CUIT ordenante/pagador (11, num)
        f21 = self._fmt_cuit(company.vat)

        record = f1 + f2 + f3 + f4 + f5 + f6 + f7 + f8 + f9 + f10 + \
                 f11 + f12 + f13 + f14 + f15 + f16 + f17 + f18 + f19 + f20 + f21

        # Tip: este assert falla en desarrollo si algún campo tiene longitud incorrecta,
        # facilitando el diagnóstico antes de llegar a SICORE
        assert len(record) == 198, (
            'Registro SICORE con longitud %d (esperado 198). '
            'Pago: %s | Factura: %s' % (
                len(record),
                payment.name,
                inv.name if inv else 'anticipo',
            )
        )
        return record

    # ── Datos para el PDF ─────────────────────────────────────────────────────

    def _build_pdf_data(self, payments):
        """Prepara los datos que consume el template QWeb del reporte PDF.

        Retorna (payments_data, total_retenido) donde payments_data es una
        lista de dicts con la info de cada pago de retención.
        """
        payments_data = []
        total_retenido = 0.0
        for payment in payments:
            pg = payment.payment_group_id
            partner = pg.commercial_partner_id if pg else payment.partner_id
            regimen = ''
            if pg and pg.regimen_ganancias_id:
                regimen = pg.regimen_ganancias_id.display_name or ''

            invoices_data = []
            invoices = self._get_invoices_for_payment(payment)
            for inv in invoices:
                invoices_data.append({
                    'name': inv.name or '',
                    'date': inv.invoice_date,
                    'untaxed': inv.amount_untaxed,
                    'total': inv.amount_total,
                })

            payments_data.append({
                'date': payment.date,
                'partner': partner.name or '',
                'cuit': partner.vat or '',
                'withholding_number': payment.withholding_number or payment.name or '',
                'regimen': regimen,
                'amount': payment.amount,
                'invoices': invoices_data,
            })
            total_retenido += payment.amount

        return payments_data, total_retenido

    # ── Generador del TXT ─────────────────────────────────────────────────────

    def _build_txt(self, payments):
        """Genera el TXT SICORE: un registro de 198 chars por factura por pago.

        Por qué: Opción B — un registro por factura asociada al pago.
        Base e importe de retención se prorratean proporcionalmente
        al importe de cada factura respecto al total del payment group.
        Si no hay facturas (anticipo), se genera un único registro con
        el monto total del pago.
        """
        lines = []
        for payment in payments:
            invoices = self._get_invoices_for_payment(payment)
            base_total = payment.withholding_base_amount or 0.0
            ret_total = payment.amount or 0.0

            if not invoices:
                # Anticipo sin factura: un solo registro con el total
                lines.append(self._build_record(payment, False, base_total, ret_total))
                continue

            # Prorrateo: base e importe se distribuyen proporcionalmente
            # al importe de cada factura respecto al total del grupo
            total_facturas = sum(abs(inv.amount_total) for inv in invoices)
            for inv in invoices:
                if total_facturas:
                    proporcion = abs(inv.amount_total) / total_facturas
                else:
                    # Por qué: evitar división por cero si todos los importes son 0
                    proporcion = 1.0 / len(invoices)
                lines.append(self._build_record(
                    payment, inv,
                    base_total * proporcion,
                    ret_total * proporcion,
                ))

        return '\r\n'.join(lines) + '\r\n'

    # ── Acción principal ──────────────────────────────────────────────────────

    def action_generate(self):
        """Genera el TXT SICORE (posición fija 198 chars) + reporte PDF."""
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('La fecha "Desde" debe ser anterior a "Hasta".'))

        payments = self._get_withholding_payments()

        txt_content = self._build_txt(payments)
        self.file_txt = base64.b64encode(txt_content.encode('utf-8'))
        self.file_txt_name = 'SICORE_retenciones_%s.txt' % self.period

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
