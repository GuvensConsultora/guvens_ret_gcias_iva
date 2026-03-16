# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import UserError


class AccountTax(models.Model):
    """Agrega diario específico por impuesto de retención.
    Por qué: el código OCA tiene un bug que siempre toma el primer
    diario tipo Efectivo (compara payment_method.id consigo mismo).
    Este campo permite asignar un diario específico a cada impuesto
    de retención (ej: "Retenciones IIBB ARBA", "Retenciones Ganancias").
    """
    _inherit = 'account.tax'

    # Por qué: sin este campo, el motor OCA busca cualquier diario cash
    # con método Withholding y toma el primero que encuentra (bug).
    # Con este campo, cada impuesto de retención apunta a su diario.
    withholding_journal_id = fields.Many2one(
        'account.journal',
        string='Diario de Retención',
        domain=[('type', '=', 'cash')],
        help='Diario específico para esta retención. '
             'Si está vacío, busca el primer diario tipo Efectivo '
             'con método de pago Withholding.',
    )

    def get_withholding_vals(self, payment_group):
        """Fix: OCA no guarda el resultado de la escala en period_withholding_amount.
        Bug OCA (l10n_ar_account_withholding_automatic/models/account_tax.py):
        - Línea 167: calcula period_withholding_amount = base × porcentaje_inscripto / 100
          Para regímenes con escala (porcentaje_inscripto = -1), esto da un valor NEGATIVO.
        - Línea 173-197: recalcula correctamente con la escala de ganancias.
        - Línea 217: vals['period_withholding_amount'] = amount ← COMENTADO, nunca se guarda.
        Resultado: la retención queda negativa → el motor la trata como $0.
        Fix: después de super(), si el régimen usa escala, recalculamos con la escala
        y guardamos el resultado en vals['period_withholding_amount'].
        """
        vals = super().get_withholding_vals(payment_group)

        # Solo aplica a tabla_ganancias con escala (porcentaje_inscripto = -1)
        if self.withholding_type != 'tabla_ganancias':
            return vals

        regimen = payment_group.regimen_ganancias_id
        if not regimen or regimen.porcentaje_inscripto != -1:
            return vals

        commercial_partner = payment_group.commercial_partner_id
        if commercial_partner.imp_ganancias_padron != 'AC':
            return vals

        # Recalcular con la escala usando la base que OCA ya computó
        base_amount = vals.get('withholdable_base_amount', 0.0)
        if base_amount <= 0:
            return vals

        escala = self.env['afip.tabla_ganancias.escala'].search([
            ('importe_desde', '<=', base_amount),
            ('importe_hasta', '>', base_amount),
        ], limit=1)
        if not escala:
            return vals

        # Cálculo correcto: importe_fijo + (base - excedente) × porcentaje
        amount = escala.importe_fijo + (escala.porcentaje / 100.0) * (
            base_amount - escala.importe_excedente)

        # Guardar el resultado que OCA dejó comentado
        vals['period_withholding_amount'] = amount
        vals['comment'] = "%s + (%s x %s)" % (
            escala.importe_fijo,
            base_amount - escala.importe_excedente,
            escala.porcentaje / 100.0)

        return vals

    def create_payment_withholdings(self, payment_group):
        """Override que corrige la selección de diario.
        Bug OCA: `if payment_method.id == payment_method.id` → siempre True.
        Fix: usa withholding_journal_id del impuesto si está configurado,
        sino busca correctamente el diario con método Withholding.
        """
        for tax in self.filtered(lambda x: x.withholding_type != 'none'):
            payment_withholding = self.env['account.payment'].search([
                ('payment_group_id', '=', payment_group.id),
                ('tax_withholding_id', '=', tax.id),
                ('automatic', '=', True),
            ], limit=1)

            # Validación de dominio de error del usuario (lógica OCA original)
            if tax.withholding_user_error_message and tax.withholding_user_error_domain:
                try:
                    from ast import literal_eval
                    domain = literal_eval(tax.withholding_user_error_domain)
                except Exception as e:
                    raise UserError(_(
                        'Could not eval rule domain "%s".\n'
                        'This is what we get:\n%s' % (
                            tax.withholding_user_error_domain, e)))
                domain.append(('id', '=', payment_group.id))
                if payment_group.search(domain):
                    raise UserError(tax.withholding_user_error_message)

            vals = tax.get_withholding_vals(payment_group)

            # Redondeo de montos (lógica OCA original)
            currency = payment_group.currency_id
            period_withholding_amount = currency.round(
                vals.get('period_withholding_amount', 0.0))
            previous_withholding_amount = currency.round(
                vals.get('previous_withholding_amount'))
            computed_withholding_amount = max(
                0, period_withholding_amount - previous_withholding_amount)

            if not computed_withholding_amount:
                if payment_withholding:
                    payment_withholding.unlink()
                continue

            vals['withholding_base_amount'] = (
                vals.get('withholdable_advanced_amount') +
                vals.get('withholdable_invoiced_amount'))
            vals['amount'] = computed_withholding_amount
            vals['computed_withholding_amount'] = computed_withholding_amount
            vals.pop('comment')

            if payment_withholding:
                payment_withholding.write(vals)
            else:
                payment_method = self.env.ref(
                    'account_withholding.account_payment_method_out_withholding')

                # FIX: usa withholding_journal_id del impuesto si está configurado
                journal = tax.withholding_journal_id
                if not journal:
                    # Fallback: buscar diario con método Withholding (bug OCA corregido)
                    journals = self.env['account.journal'].search([
                        ('company_id', '=', tax.company_id.id),
                        ('type', '=', 'cash'),
                    ])
                    for jour in journals:
                        for line in jour.outbound_payment_method_line_ids:
                            # FIX: comparar el método del diario (no consigo mismo)
                            if line.payment_method_id.id == payment_method.id:
                                journal = jour
                                break
                        if journal:
                            break

                if not journal:
                    raise UserError(_(
                        'No hay diario de retenciones definido para '
                        'el impuesto "%s" en la empresa %s.\n'
                        'Configure el campo "Diario de Retención" en el '
                        'impuesto o agregue el método Withholding a un '
                        'diario tipo Efectivo.') % (
                            tax.name, tax.company_id.name))

                vals['journal_id'] = journal.id
                vals['payment_method_id'] = payment_method.id
                vals['payment_type'] = 'outbound'
                vals['partner_type'] = payment_group.partner_type
                vals['partner_id'] = payment_group.partner_id.id
                payment_withholding = payment_withholding.create(vals)
        return True
