# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    has_filament_moves = fields.Boolean(
        string='Tiene filamento 3D', compute='_compute_has_filament_moves')

    @api.depends('move_lines.product_id')
    def _compute_has_filament_moves(self):
        for picking in self:
            picking.has_filament_moves = any(picking.move_lines.mapped('product_id.is_filament'))

    def action_open_spool_receive_wizard(self):
        self.ensure_one()
        return {
            'name': _('Generar carretes'),
            'type': 'ir.actions.act_window',
            'res_model': 'imago.spool.receive.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_picking_id': self.id},
        }
