# -*- coding: utf-8 -*-
from datetime import date
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
            # _chatter_detail es un dict auxiliar interno, no un campo del modelo
            chatter_detail = vals.pop('_chatter_detail', None)

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

    def _get_ganancias_accumulated(self, payment_group):
        """Override: acumular base imponible y retenciones previas del mes.

        Bug OCA (l10n_ar_account_withholding): el método original itera sobre
        account.payment y por cada pago recorre matched_move_line_ids del PG
        padre, produciendo double-counting cuando el PG tiene N pagos y M
        líneas conciliadas (suma N×M veces las mismas líneas).

        Fix: iterar sobre payment_groups del mes y sumar matched_amount_untaxed
        + ajuste/adelanto por cada PG una sola vez. Esto cumple RG 830 art. 26
        (acumulación mensual por beneficiario).
        """
        today = payment_group.payment_date
        first_day = date(today.year, today.month, 1)

        prev_pgs = self.env['account.payment.group'].search([
            ('partner_id', '=', payment_group.partner_id.id),
            ('regimen_ganancias_id', '=',
                payment_group.regimen_ganancias_id.id),
            ('retencion_ganancias', '=', 'nro_regimen'),
            ('state', '=', 'posted'),
            ('payment_date', '>=', str(first_day)),
            ('payment_date', '<=', today),
            ('id', '!=', payment_group.id),
        ])

        accumulated_amount = 0.0
        for pg in prev_pgs:
            # Base neta de facturas conciliadas
            if pg.matched_amount_untaxed:
                accumulated_amount += pg.matched_amount_untaxed
            elif pg.matched_move_line_ids:
                # Fallback: cuando matched_amount_untaxed no está computado,
                # recorrer las líneas conciliadas y armar el neto manualmente
                # usando el tax_factor (ratio neto/total) de cada factura.
                for line in pg.matched_move_line_ids:
                    tax_factor = line.move_id._get_tax_factor() or 1.0
                    matched_amt = line.with_context(
                        payment_group_id=pg.id
                    ).payment_group_matched_amount
                    accumulated_amount += abs(matched_amt) * tax_factor
            # + Adelanto/ajuste del PG (unreconciled_amount como fallback
            # por el onchange UI-only de withholdable_advanced_amount
            # que no se dispara en escrituras ORM)
            accumulated_amount += (
                pg.withholdable_advanced_amount
                or pg.unreconciled_amount
                or 0.0
            )

        # Retenciones ya practicadas de este mismo tax
        prev_wh_payments = self.env['account.payment'].search([
            ('payment_type', '=', 'outbound'),
            ('state', '=', 'posted'),
            ('partner_id', '=', payment_group.partner_id.id),
            ('tax_withholding_id', '=', self.id),
            ('payment_group_id', 'in', prev_pgs.ids),
        ])
        previous_withholding = sum(prev_wh_payments.mapped('amount'))

        return accumulated_amount, previous_withholding, bool(previous_withholding)
