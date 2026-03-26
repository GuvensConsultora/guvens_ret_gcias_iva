# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import UserError

MESES = [
    ('1', 'Enero'), ('2', 'Febrero'), ('3', 'Marzo'),
    ('4', 'Abril'), ('5', 'Mayo'), ('6', 'Junio'),
    ('7', 'Julio'), ('8', 'Agosto'), ('9', 'Septiembre'),
    ('10', 'Octubre'), ('11', 'Noviembre'), ('12', 'Diciembre'),
]

# Escala ANUAL Art. 94 LIG — 2026 (fuente: ARCA, ene-dic 2026)
# Cada mes acumulado = valor_anual × mes / 12
# Actualizar estos valores solo cuando ARCA publique nueva escala anual.
ESCALA_ANUAL = [
    # (importe_desde, importe_hasta, importe_fijo, porcentaje, importe_excedente)
    (0.00,          2000030.09,  0.00,        5,  0.00),
    (2000030.09,    4000060.17,  100001.50,   9,  2000030.09),
    (4000060.17,    6000090.26,  280004.21,   12, 4000060.17),
    (6000090.26,    9000135.40,  520007.82,   15, 6000090.26),
    (9000135.40,    18000270.80, 970014.59,   19, 9000135.40),
    (18000270.80,   27000406.20, 2680040.32,  23, 18000270.80),
    (27000406.20,   40500609.30, 4750071.46,  27, 27000406.20),
    (40500609.30,   60750913.96, 8395126.30,  31, 40500609.30),
    (60750913.96,   None,        14672720.74, 35, 60750913.96),
]


class TablaGananciasImportWizard(models.TransientModel):
    _name = 'tabla.ganancias.import.wizard'
    _description = 'Actualizar escala de Ganancias'

    mes = fields.Selection(MESES, string='Mes de pago', required=True,
                           default=lambda self: str(fields.Date.today().month))

    def action_actualizar_escala(self):
        self.ensure_one()
        mes = int(self.mes)
        factor = mes / 12.0

        vals_list = []
        for desde, hasta, fijo, porcentaje, excedente in ESCALA_ANUAL:
            vals_list.append({
                'importe_desde': round(desde * factor, 2),
                'importe_hasta': round(hasta * factor, 2) if hasta else 99999999999.0,
                'importe_fijo': round(fijo * factor, 2),
                'porcentaje': porcentaje,
                'importe_excedente': round(excedente * factor, 2),
            })

        Escala = self.env['afip.tabla_ganancias.escala']
        Escala.search([]).unlink()
        Escala.create(vals_list)

        mes_label = dict(MESES)[self.mes]
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Escala actualizada'),
                'message': _('Escala %s: %d tramos cargados.') % (
                    mes_label, len(vals_list)),
                'type': 'success',
                'sticky': False,
            },
        }
