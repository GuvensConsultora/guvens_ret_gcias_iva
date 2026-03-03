# -*- coding: utf-8 -*-
from odoo import models


class AccountPayment(models.Model):
    """Helpers para el template QWeb del certificado de retención +
    override de numeración para usar la secuencia del diario.
    """
    _inherit = 'account.payment'

    # ── Numeración desde secuencia del diario ─────────────────

    def post(self):
        """Override: asigna withholding_number desde la secuencia del diario
        configurado en withholding_journal_id del impuesto.
        Por qué: el OCA original usa tax.withholding_sequence_id, pero
        el usuario quiere que el nro de certificado venga del diario
        de retención (ej: secuencia del diario "Retenciones IIBB ARBA").
        """
        for payment in self.filtered(
            lambda p: p.tax_withholding_id and not p.withholding_number
        ):
            # Prioridad: secuencia del diario configurado en el impuesto
            journal = payment.tax_withholding_id.withholding_journal_id
            if journal and journal.sequence_id:
                payment.withholding_number = journal.sequence_id.next_by_id()
        return super().post()

    # ── Tipo de retención ──────────────────────────────────────

    def is_iibb_withholding(self):
        """True si la retención es IIBB (tipo partner_tax en el impuesto).
        Por qué: el template usa t-if para mostrar secciones condicionales
        según el tipo de impuesto (IIBB vs Ganancias).
        """
        self.ensure_one()
        return self.tax_withholding_id.withholding_type == 'partner_tax'

    def is_ganancias_withholding(self):
        """True si la retención es Ganancias (tipo tabla_ganancias).
        Por qué: Ganancias tiene campos específicos (régimen, concepto)
        que no aplican a IIBB.
        """
        self.ensure_one()
        return self.tax_withholding_id.withholding_type == 'tabla_ganancias'

    # ── Etiqueta del certificado ───────────────────────────────

    def get_withholding_type_label(self):
        """Devuelve etiqueta legible para el título del certificado.
        Patrón: dispatch por tipo de retención → etiqueta descriptiva.
        """
        self.ensure_one()
        wh_type = self.tax_withholding_id.withholding_type
        if wh_type == 'partner_tax':
            return "IIBB Buenos Aires"
        elif wh_type == 'tabla_ganancias':
            return "Impuesto a las Ganancias"
        return self.tax_withholding_id.display_name or "Retención"

    # ── Alícuota aplicada ──────────────────────────────────────

    def get_withholding_alicuota(self):
        """Devuelve el % de alícuota aplicado en la retención.
        Por qué: la alícuota viene de distintas fuentes según el tipo:
        - IIBB (partner_tax): res.partner.perception del partner
        - Ganancias (tabla_ganancias): regimen_ganancias_id.porcentaje_inscripto
        """
        self.ensure_one()
        wh_type = self.tax_withholding_id.withholding_type

        if wh_type == 'partner_tax':
            # IIBB: buscar la alícuota en perception_ids del partner
            perception = self.env['res.partner.perception'].search([
                ('partner_id', '=', self.payment_group_id.commercial_partner_id.id),
                ('tax_id', '=', self.tax_withholding_id.id),
            ], limit=1)
            return perception.percent if perception else 0.0

        elif wh_type == 'tabla_ganancias':
            # Ganancias: alícuota del régimen seleccionado en el payment group
            regimen = self.payment_group_id.regimen_ganancias_id
            if regimen:
                # Por qué: porcentaje_inscripto = -1 indica cálculo por escala
                # En ese caso mostramos -1 y el template lo interpreta
                return regimen.porcentaje_inscripto
            return 0.0

        return 0.0

    # ── Facturas asociadas ─────────────────────────────────────

    def get_withholding_invoices(self):
        """Devuelve las facturas/NC asociadas al payment group.
        Por qué: reemplaza o.reconciled_invoice_ids que NO existe en account.payment.
        Ruta: payment_group_id → matched_move_line_ids → move_id (facturas).
        """
        self.ensure_one()
        if not self.payment_group_id:
            return self.env['account.move']
        # Filtrar solo facturas/NC (no asientos contables internos)
        moves = self.payment_group_id.matched_move_line_ids.mapped('move_id')
        return moves.filtered(
            lambda m: m.move_type in ('in_invoice', 'in_refund', 'out_invoice', 'out_refund')
        )

    # ── Régimen Ganancias (datos extra) ────────────────────────

    def get_regimen_ganancias_label(self):
        """Devuelve texto descriptivo del régimen de ganancias.
        Formato: 'Código - Concepto' para el certificado.
        """
        self.ensure_one()
        regimen = self.payment_group_id.regimen_ganancias_id
        if not regimen:
            return ""
        return "%s - %s" % (
            regimen.codigo_de_regimen or '',
            regimen.concepto_referencia or '',
        )
