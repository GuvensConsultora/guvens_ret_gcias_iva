import base64
from odoo import models, fields, _
from markupsafe import Markup


class AccountPaymentGroup(models.Model):
    """Override para trackear TODO el proceso de cálculo de retenciones en el chatter.
    Por qué: el motor OCA calcula en silencio. Este override reemplaza
    compute_withholdings() con una versión que loguea cada paso en el chatter
    del Payment Group, y luego ejecuta el cálculo real.
    """
    _inherit = 'account.payment.group'

    def action_payment_sent(self):
        """Enviar por email: adjunta Orden de Pago + certificados de retención.
        Por qué: el OCA solo adjunta el recibo. El usuario necesita enviar
        al proveedor todos los comprobantes juntos en un solo email.
        """
        self.ensure_one()
        # Por qué: busca template en arba (módulo hermano) si está instalado
        template = self.env.ref(
            'guvens_ret_gcias_iva.email_template_payment_group', False
        ) or self.env.ref('arba.email_template_payment_group', False)
        compose_form = self.env.ref(
            'mail.email_compose_message_wizard_form', False)

        # Generar adjuntos: Orden de Pago + Certificados de Retención
        attachment_ids = self._generate_payment_attachments()

        ctx = dict(
            default_model='account.payment.group',
            default_res_ids=self.ids,
            default_use_template=bool(template),
            default_template_id=template and template.id or False,
            default_composition_mode='comment',
            # Por qué: adjuntos pre-generados para que aparezcan en el wizard
            default_attachment_ids=attachment_ids,
            mark_payment_as_sent=True,
        )
        return {
            'name': _('Compose Email'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'mail.compose.message',
            'views': [(compose_form.id, 'form')],
            'view_id': compose_form.id,
            'target': 'new',
            'context': ctx,
        }

    def _generate_payment_attachments(self):
        """Genera PDFs de Orden de Pago + certificados y devuelve lista de IDs.
        Por qué: mail.compose.message necesita ir.attachment ya creados
        para mostrarlos en el wizard antes de enviar.
        """
        self.ensure_one()
        Attachment = self.env['ir.attachment']
        attachment_ids = []

        # 1. PDF Orden de Pago (recibo del payment group)
        report_pg = self.env.ref(
            'l10n_ar_report_payment_group.account_payment_group_report', False)
        if report_pg:
            pdf_content, _ = report_pg._render_qweb_pdf(
                report_pg.report_name, res_ids=self.ids)
            att = Attachment.create({
                'name': 'Orden de Pago - %s.pdf' % (self.display_name or ''),
                'type': 'binary',
                'datas': base64.b64encode(pdf_content),
                'res_model': 'account.payment.group',
                'res_id': self.id,
                'mimetype': 'application/pdf',
            })
            attachment_ids.append(att.id)

        # 2. PDF Certificado de Retención por cada pago de retención
        # Por qué: cada retención genera un certificado independiente
        withholding_payments = self.payment_ids.filtered(
            lambda p: p.tax_withholding_id)
        if withholding_payments:
            report_wh = self.env.ref(
                'l10n_ar_report_withholding.action_payment_withholdings', False)
            if report_wh:
                for payment in withholding_payments:
                    pdf_content, _ = report_wh._render_qweb_pdf(
                        report_wh.report_name, res_ids=payment.ids)
                    att = Attachment.create({
                        'name': 'Certificado Retención - %s.pdf' % (
                            payment.withholding_number or payment.name),
                        'type': 'binary',
                        'datas': base64.b64encode(pdf_content),
                        'res_model': 'account.payment',
                        'res_id': payment.id,
                        'mimetype': 'application/pdf',
                    })
                    attachment_ids.append(att.id)

        return attachment_ids

    def compute_withholdings(self):
        # Por qué: verificar si el módulo arba está instalado
        # para habilitar checks de padrón ARBA en la checklist diagnóstica
        has_arba = 'arba.padron' in self.env

        for rec in self:
            if rec.partner_type != 'supplier':
                continue

            partner = rec.commercial_partner_id
            cuit = (partner.vat or '').replace('-', '')

            # =============================================
            # PASO 1: INICIO — Datos del pago
            # =============================================
            msg = Markup('<div style="background:#f0f4ff;padding:14px;border-radius:8px;'
                         'border:1px solid #b0c4de;font-size:13px;">')
            msg += Markup('<h3 style="margin:0 0 10px 0;color:#1a3e5c;">'
                         'Tracking Retenciones — Paso a paso</h3>')

            msg += Markup('<div style="background:#e8f0fe;padding:10px;border-radius:6px;margin-bottom:10px;">')
            msg += Markup('<b>PASO 1: Datos del pago</b><br/>')
            msg += Markup('Partner: <b>%s</b><br/>') % partner.name
            msg += Markup('CUIT: <b>%s</b><br/>') % (partner.vat or 'SIN CUIT')
            msg += Markup('Provincia: <b>%s</b> (ID: %s)<br/>') % (
                partner.state_id.name or 'Sin provincia', partner.state_id.id or '-')
            msg += Markup('Fecha de pago: <b>%s</b><br/>') % (rec.payment_date or '-')
            msg += Markup('Monto a pagar: <b>%s</b><br/>') % f"{rec.to_pay_amount:,.2f}"
            msg += Markup('automatic_withholdings: %s') % (
                Markup('<b style="color:green;">SI</b>') if rec.company_id.automatic_withholdings
                else Markup('<b style="color:red;">NO</b>'))
            msg += Markup('</div>')

            # =============================================
            # PASO 2: BÚSQUEDA — Impuestos de retención
            # =============================================
            all_taxes = self.env['account.tax'].with_context(type=None).search([
                ('type_tax_use', '=', rec.partner_type),
                ('company_id', '=', rec.company_id.id),
            ])
            withholding_taxes = all_taxes.filtered(lambda x: x.withholding_type != 'none')
            no_withholding_taxes = all_taxes.filtered(lambda x: x.withholding_type == 'none')

            msg += Markup('<div style="background:#e8f0fe;padding:10px;border-radius:6px;margin-bottom:10px;">')
            msg += Markup('<b>PASO 2: Búsqueda de impuestos supplier</b><br/>')
            msg += Markup('Total impuestos supplier: <b>%s</b><br/>') % len(all_taxes)
            msg += Markup('Con retención activa (withholding_type != none): <b>%s</b><br/>') % len(withholding_taxes)
            msg += Markup('Sin retención (se ignoran): <b>%s</b><br/>') % len(no_withholding_taxes)

            if withholding_taxes:
                msg += Markup('<br/><u>Impuestos que se van a evaluar:</u><br/>')
                for tax in withholding_taxes:
                    msg += Markup('&nbsp;&nbsp;- %s (tipo: %s, amount: %s)<br/>') % (
                        tax.name, tax.withholding_type, tax.amount)
            else:
                msg += Markup('<br/><span style="color:red;font-weight:bold;">'
                              'No hay impuestos con retención activa. El proceso termina acá.</span>')
            msg += Markup('</div>')

            # =============================================
            # PASO 3: EVALUACIÓN — Por cada impuesto
            # =============================================
            paso = 2
            for tax in withholding_taxes:
                paso += 1
                color_borde = '#4a90d9'

                msg += Markup('<div style="background:#fff;padding:10px;border-radius:6px;'
                              'margin-bottom:10px;border-left:4px solid %s;">') % color_borde
                msg += Markup('<b>PASO %s: Evaluar "%s"</b><br/>') % (paso, tax.name)
                msg += Markup('withholding_type: <b>%s</b><br/>') % tax.withholding_type
                msg += Markup('withholding_amount_type: <b>%s</b><br/>') % (
                    tax.withholding_amount_type or 'NO CONFIGURADO')
                msg += Markup('Mínimo no imponible: <b>%s</b><br/>') % f"{tax.withholding_non_taxable_minimum:,.2f}"
                msg += Markup('Monto no imponible: <b>%s</b><br/>') % f"{tax.withholding_non_taxable_amount:,.2f}"
                msg += Markup('Pagos acumulados: <b>%s</b><br/>') % (
                    tax.withholding_accumulated_payments or 'No acumula')

                # --- 3a: Verificar retención existente ---
                existing_payment = self.env['account.payment'].search([
                    ('payment_group_id', '=', rec.id),
                    ('tax_withholding_id', '=', tax.id),
                    ('automatic', '=', True),
                ], limit=1)
                if existing_payment:
                    msg += Markup('Retención existente: <b>SI</b> (pago %s por %s)<br/>') % (
                        existing_payment.name, f"{existing_payment.amount:,.2f}")
                else:
                    msg += Markup('Retención existente: <b>NO</b> (se creará si corresponde)<br/>')

                # --- 3b: Según tipo de retención ---
                if tax.withholding_type == 'partner_tax':
                    msg += Markup('<br/><u>Tipo: Alícuota en el Partner</u><br/>')

                    # Buscar perception_ids
                    perceptions = self.env['res.partner.perception'].search([
                        ('partner_id', '=', partner.id),
                        ('tax_id', '=', tax.id),
                    ])
                    all_partner_perceptions = self.env['res.partner.perception'].search([
                        ('partner_id', '=', partner.id),
                    ])

                    msg += Markup('Total perception_ids del partner: <b>%s</b><br/>') % len(all_partner_perceptions)
                    if all_partner_perceptions:
                        for p in all_partner_perceptions:
                            match = ' (MATCH)' if p.tax_id.id == tax.id else ''
                            color = 'green' if p.tax_id.id == tax.id else 'gray'
                            msg += Markup('&nbsp;&nbsp;- tax: %s, percent: %s%%%s<br/>') % (
                                p.tax_id.name,
                                p.percent,
                                Markup('<b style="color:%s;">%s</b>') % (color, match))

                    if perceptions:
                        perc = perceptions[0]
                        msg += Markup('<br/>Alícuota encontrada: <b style="color:green;">%s%%</b><br/>') % perc.percent
                    else:
                        msg += Markup('<br/><span style="color:red;font-weight:bold;">'
                                      'NO se encontró perception para tax "%s" en este partner</span><br/>') % tax.name
                        # Buscar en padrón ARBA (solo si el módulo arba está instalado)
                        if has_arba:
                            padron_ret = self.env['arba.padron'].search([
                                ('cuit', '=', cuit), ('tipo', '=like', 'R%'),
                            ], limit=1)
                            if padron_ret:
                                msg += Markup('<span style="color:orange;">'
                                              'El padrón ARBA tiene tasa %s%% para CUIT %s, '
                                              'pero no se cargó en perception_ids. '
                                              'Ejecute "Procesar ZIP" para cargarla.</span><br/>') % (
                                                  padron_ret.tasa, cuit)
                            else:
                                msg += Markup('<span style="color:gray;">'
                                              'CUIT %s NO está en el padrón de retenciones.</span><br/>') % cuit

                    # Ejecutar get_partner_alicuot
                    alicuota = tax.get_partner_alicuot(
                        partner, rec.payment_date or fields.Date.context_today(self))
                    msg += Markup('get_partner_alicuot() devuelve: <b>%s</b><br/>') % alicuota

                elif tax.withholding_type == 'tabla_ganancias':
                    msg += Markup('<br/><u>Tipo: Tabla Ganancias</u><br/>')
                    msg += Markup('retencion_ganancias: <b>%s</b><br/>') % (
                        rec.retencion_ganancias or 'NO SELECCIONADO')
                    if rec.retencion_ganancias == 'nro_regimen':
                        msg += Markup('regimen_ganancias_id: <b>%s</b><br/>') % (
                            rec.regimen_ganancias_id.display_name or 'VACÍO')
                    msg += Markup('imp_ganancias_padron del partner: <b>%s</b><br/>') % (
                        partner.imp_ganancias_padron or 'NO CONFIGURADO')
                    if rec.retencion_ganancias != 'nro_regimen' or not rec.regimen_ganancias_id:
                        msg += Markup('<span style="color:orange;">'
                                      'Sin régimen seleccionado → retención Ganancias = 0</span><br/>')

                elif tax.withholding_type == 'based_on_rule':
                    msg += Markup('<br/><u>Tipo: Basado en Regla</u><br/>')
                    rule = tax._get_rule(rec)
                    if rule:
                        msg += Markup('Regla: percentage=%s, fix_amount=%s<br/>') % (
                            rule.percentage, rule.fix_amount)
                    else:
                        msg += Markup('<span style="color:red;">No se encontró regla aplicable</span><br/>')

                elif tax.withholding_type == 'code':
                    msg += Markup('<br/><u>Tipo: Python Code</u><br/>')
                    msg += Markup('Código configurado: <b>SI</b><br/>')

                # --- 3c: Calcular montos (get_withholding_vals) ---
                msg += Markup('<br/><u>Cálculo de montos:</u><br/>')
                try:
                    vals = tax.get_withholding_vals(rec)

                    withholdable_invoiced = vals.get('withholdable_invoiced_amount', 0)
                    withholdable_advanced = vals.get('withholdable_advanced_amount', 0)
                    accumulated = vals.get('accumulated_amount', 0)
                    total = vals.get('total_amount', 0)
                    non_taxable_min = vals.get('withholding_non_taxable_minimum', 0)
                    non_taxable_amt = vals.get('withholding_non_taxable_amount', 0)
                    base = vals.get('withholdable_base_amount', 0)
                    period_amount = vals.get('period_withholding_amount', 0)
                    prev_amount = vals.get('previous_withholding_amount', 0)
                    comment = vals.get('comment', '')

                    currency = rec.currency_id
                    period_rounded = currency.round(period_amount)
                    prev_rounded = currency.round(prev_amount)
                    computed = max(0, period_rounded - prev_rounded)

                    msg += Markup('Monto facturado retenible: <b>%s</b><br/>') % f"{withholdable_invoiced:,.2f}"
                    msg += Markup('Monto adelanto retenible: <b>%s</b><br/>') % f"{withholdable_advanced:,.2f}"
                    msg += Markup('Pagos acumulados período: <b>%s</b><br/>') % f"{accumulated:,.2f}"
                    msg += Markup('Total amount: <b>%s</b><br/>') % f"{total:,.2f}"
                    msg += Markup('Mínimo no imponible: <b>%s</b> (total > mínimo? %s)<br/>') % (
                        f"{non_taxable_min:,.2f}",
                        Markup('<b style="color:green;">SI</b>') if total > non_taxable_min
                        else Markup('<b style="color:red;">NO → base = 0</b>'))
                    msg += Markup('Monto no imponible a restar: <b>%s</b><br/>') % f"{non_taxable_amt:,.2f}"
                    msg += Markup('Base imponible (total - no imponible): <b>%s</b><br/>') % f"{base:,.2f}"

                    msg += Markup('<br/><div style="background:#f5f5f5;padding:8px;border-radius:4px;">')
                    msg += Markup('Retención del período: <b>%s</b><br/>') % f"{period_rounded:,.2f}"
                    msg += Markup('Retenciones previas: <b>%s</b><br/>') % f"{prev_rounded:,.2f}"
                    msg += Markup('Cálculo: %s<br/>') % (comment or '-')

                    if computed > 0:
                        msg += Markup('<b style="color:green;font-size:14px;">'
                                      'RETENCIÓN A CREAR: %s</b>') % f"{computed:,.2f}"
                    else:
                        msg += Markup('<b style="color:red;font-size:14px;">'
                                      'RETENCIÓN = 0 → No se crea pago</b>')

                        # Por qué: cuando la retención da 0, el usuario necesita
                        # saber qué parametrizar. Armamos checklist diagnóstica
                        # evaluando cada condición que pudo fallar.
                        msg += Markup('</div>')
                        msg += Markup('<div style="background:#fff3cd;padding:10px;'
                                      'border-radius:6px;margin-top:8px;'
                                      'border-left:4px solid #ffc107;">')
                        msg += Markup('<b style="color:#856404;">Checklist de parametrización</b><br/>')
                        msg += Markup('<span style="font-size:12px;color:#664d03;">'
                                      'Revisá estos puntos para que la retención se calcule:</span><br/><br/>')

                        # Check 1: Padrón ARBA cargado (solo si módulo arba instalado)
                        if has_arba:
                            padron_count = self.env['arba.padron'].search_count([
                                ('tipo', '=like', 'R%'),
                            ])
                            padron_partner = self.env['arba.padron'].search([
                                ('cuit', '=', cuit), ('tipo', '=like', 'R%'),
                            ], limit=1)
                            if padron_count == 0:
                                msg += Markup('<span style="color:red;">&#10060;</span> '
                                              '<b>1. Subir padrón ARBA:</b> '
                                              'No hay registros de retención cargados. '
                                              'Ir a <i>ARBA → Archivo Comprimido</i> → subir ZIP del padrón '
                                              '(debe contener archivo Ret*.txt)<br/>')
                            elif not padron_partner:
                                msg += Markup('<span style="color:orange;">&#9888;</span> '
                                              '<b>1. Padrón cargado</b> (%s registros Ret), '
                                              'pero CUIT %s <b>no figura</b>. '
                                              'Verificar que el padrón sea el vigente del período.<br/>') % (
                                                  padron_count, cuit)
                            else:
                                msg += Markup('<span style="color:green;">&#9989;</span> '
                                              '<b>1. Padrón OK:</b> CUIT %s encontrado '
                                              'con tasa %s%%<br/>') % (cuit, padron_partner.tasa)

                        # Check 2: Perception cargada en el partner
                        perc_partner = self.env['res.partner.perception'].search([
                            ('partner_id', '=', partner.id),
                            ('tax_id', '=', tax.id),
                        ], limit=1)
                        if not perc_partner:
                            msg += Markup('<span style="color:red;">&#10060;</span> '
                                          '<b>2. Cargar alícuota en partner:</b> '
                                          '%s no tiene alícuota para "%s". ') % (partner.name, tax.name)
                            if has_arba:
                                padron_partner = self.env['arba.padron'].search([
                                    ('cuit', '=', cuit), ('tipo', '=like', 'R%'),
                                ], limit=1)
                                if padron_partner:
                                    msg += Markup('El padrón tiene tasa %s%%. '
                                                  'Ejecutar <i>"Actualizar Posición Impositiva"</i> '
                                                  'en Archivo Comprimido para cargarla automáticamente.<br/>') % padron_partner.tasa
                                else:
                                    msg += Markup('Cargar manualmente en el partner → '
                                                  'pestaña <i>Percepciones/Retenciones</i> → '
                                                  'agregar línea con impuesto "%s" y el porcentaje.<br/>') % tax.name
                            else:
                                msg += Markup('Cargar manualmente en el partner → '
                                              'pestaña <i>Percepciones/Retenciones</i> → '
                                              'agregar línea con impuesto "%s" y el porcentaje.<br/>') % tax.name
                        elif perc_partner.percent == 0:
                            msg += Markup('<span style="color:orange;">&#9888;</span> '
                                          '<b>2. Alícuota en 0%%:</b> '
                                          'El partner tiene la línea pero con porcentaje 0. '
                                          'Editar en partner → <i>Percepciones/Retenciones</i>.<br/>')
                        else:
                            msg += Markup('<span style="color:green;">&#9989;</span> '
                                          '<b>2. Alícuota OK:</b> %s%% configurada<br/>') % perc_partner.percent

                        # Check 3: Retenciones automáticas en la compañía
                        if rec.company_id.automatic_withholdings:
                            msg += Markup('<span style="color:green;">&#9989;</span> '
                                          '<b>3. Retenciones automáticas:</b> activado<br/>')
                        else:
                            msg += Markup('<span style="color:red;">&#10060;</span> '
                                          '<b>3. Activar retenciones automáticas:</b> '
                                          'Ir a <i>Ajustes → Contabilidad</i> → '
                                          'activar "Retenciones Automáticas"<br/>')

                        # Check 4: Diario de retenciones correcto
                        try:
                            pm_wh = self.env.ref(
                                'account_withholding.account_payment_method_out_withholding')
                            wh_journals = self.env['account.journal'].search([
                                ('company_id', '=', tax.company_id.id),
                                ('type', '=', 'cash'),
                            ])
                            wh_journal = None
                            for j in wh_journals:
                                if pm_wh in j.outbound_payment_method_line_ids.mapped('payment_method_id'):
                                    wh_journal = j
                                    break
                            if wh_journal:
                                # Por qué: un diario genérico (ej: "Cheques Rechazados")
                                # técnicamente funciona pero confunde al usuario
                                name_lower = wh_journal.name.lower()
                                is_suspicious = any(w in name_lower for w in [
                                    'cheque', 'banco', 'efectivo', 'caja',
                                ])
                                if is_suspicious:
                                    msg += Markup('<span style="color:orange;">&#9888;</span> '
                                                  '<b>4. Diario:</b> "%s" tiene método Withholding '
                                                  'pero no parece ser un diario dedicado. '
                                                  'Recomendación: crear diario tipo Cash llamado '
                                                  '"Retenciones IIBB" con método de pago Withholding.<br/>') % wh_journal.name
                                else:
                                    msg += Markup('<span style="color:green;">&#9989;</span> '
                                                  '<b>4. Diario OK:</b> %s<br/>') % wh_journal.name
                            else:
                                msg += Markup('<span style="color:red;">&#10060;</span> '
                                              '<b>4. Crear diario de retenciones:</b> '
                                              'No hay diario tipo Cash con método Withholding. '
                                              'Crear uno en <i>Contabilidad → Configuración → Diarios</i> '
                                              '→ tipo Efectivo → agregar método de pago "Withholding"<br/>')
                        except Exception:
                            msg += Markup('<span style="color:red;">&#10060;</span> '
                                          '<b>4. Método Withholding no encontrado.</b> '
                                          'Verificar que el módulo account_withholding esté instalado.<br/>')

                        # Check 5: Provincia del partner
                        if not partner.state_id or partner.state_id.id != 554:
                            msg += Markup('<span style="color:orange;">&#9888;</span> '
                                          '<b>5. Provincia:</b> el partner tiene "%s". '
                                          'ARBA aplica para Buenos Aires. '
                                          'Verificar en el contacto.<br/>') % (
                                              partner.state_id.name or 'Sin provincia')
                        else:
                            msg += Markup('<span style="color:green;">&#9989;</span> '
                                          '<b>5. Provincia OK:</b> Buenos Aires<br/>')

                        msg += Markup('</div>')
                        # Por qué: cerrar el div del tax (abierto arriba)
                        # antes de saltar al siguiente impuesto
                        msg += Markup('</div>')
                        continue

                    msg += Markup('</div>')

                except Exception as e:
                    msg += Markup('<span style="color:red;font-weight:bold;">'
                                  'ERROR en get_withholding_vals(): %s</span><br/>') % str(e)

                # --- 3d: Verificar diario de retenciones ---
                # Por qué: cuando retención = 0 el diario ya se evalúa
                # en la checklist diagnóstica (continue arriba), acá solo
                # llega si computed > 0
                msg += Markup('<br/><u>Diario de retenciones:</u><br/>')
                try:
                    payment_method = self.env.ref(
                        'account_withholding.account_payment_method_out_withholding')
                    journals = self.env['account.journal'].search([
                        ('company_id', '=', tax.company_id.id),
                        ('type', '=', 'cash'),
                    ])
                    journal_found = None
                    for jour in journals:
                        for outbound in jour.outbound_payment_method_line_ids:
                            if outbound.payment_method_id.id == payment_method.id:
                                journal_found = jour
                                break
                    if journal_found:
                        msg += Markup('Diario: <b style="color:green;">%s</b><br/>') % journal_found.name
                    else:
                        msg += Markup('<span style="color:red;">No se encontró diario tipo cash '
                                      'con método de pago Withholding</span><br/>')
                except Exception as e:
                    msg += Markup('<span style="color:red;">Error buscando diario: %s</span><br/>') % str(e)

                msg += Markup('</div>')

            # =============================================
            # PASO FINAL: Resumen
            # =============================================
            paso += 1
            msg += Markup('<div style="background:#e8f0fe;padding:10px;border-radius:6px;">')
            msg += Markup('<b>PASO %s: Ejecutando cálculo real (super().compute_withholdings)</b><br/>') % paso
            msg += Markup('El motor OCA ahora ejecuta el cálculo y crea/actualiza los pagos de retención.')
            msg += Markup('</div>')

            msg += Markup('</div>')
            rec.message_post(body=msg)

        # Ejecutar el cálculo real del motor OCA
        return super().compute_withholdings()
