# -*- coding: utf-8 -*-
from odoo import fields, models


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    print_request_id = fields.Many2one(
        'imago.print.request', string='Solicitud de impresión 3D', readonly=True, copy=False, index=True)
