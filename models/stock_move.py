# -*- coding: utf-8 -*-
from odoo import fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    print_consumption_id = fields.Many2one(
        'imago.print.consumption', string='Consumo de filamento 3D', readonly=True, copy=False, index=True)
