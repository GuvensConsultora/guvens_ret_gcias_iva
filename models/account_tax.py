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
        """Fix dos bugs OCA para retención Ganancias con escala.

        Bug 1 — period_withholding_amount no se guarda:
          OCA calcula base × porcentaje_inscripto / 100. Para escala (-1),
          da negativo. Luego recalcula con escala pero la línea que guarda
          el resultado está comentada (línea 217).

        Bug 2 — monto no sujeto lee de partner en vez de payment_group:
          OCA (línea 150) usa partner.default_regimen_ganancias_id para el
          monto no sujeto. Si no está seteado en el partner, queda en $0
          y no se resta de la base. Debería usar payment_group.regimen_ganancias_id.

        Fix: después de super(), recalculamos base (restando monto no sujeto
        del régimen del payment group) y aplicamos la escala correctamente.
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

        # Fix Bug 2: recalcular base restando monto no sujeto del régimen
        # del payment group (no del partner.default_regimen_ganancias_id)
        base_amount = vals.get('total_amount', 0.0)
        non_taxable = regimen.montos_no_sujetos_a_retencion
        if base_amount < non_taxable:
            # Base menor al mínimo no sujeto → retención = 0
            vals['period_withholding_amount'] = 0.0
            return vals

        base_amount -= non_taxable
        vals['withholdable_base_amount'] = base_amount
        vals['withholding_non_taxable_amount'] = non_taxable

        if base_amount <= 0:
            vals['period_withholding_amount'] = 0.0
            return vals

        # Fix Bug 1: aplicar escala y guardar el resultado
        escala = self.env['afip.tabla_ganancias.escala'].search([
            ('importe_desde', '<=', base_amount),
            ('importe_hasta', '>', base_amount),
        ], limit=1)
        if not escala:
            return vals

        # Cálculo: importe_fijo + (base - excedente) × porcentaje
        amount = escala.importe_fijo + (escala.porcentaje / 100.0) * (
            base_amount - escala.importe_excedente)

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
