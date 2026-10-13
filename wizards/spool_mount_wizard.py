# -*- coding: utf-8 -*-
from odoo import fields, models


class SpoolMountWizard(models.TransientModel):
    _name = 'imago.spool.mount.wizard'
    _description = 'Montar carrete en impresora'

    workcenter_id = fields.Many2one(
        'mrp.workcenter', string='Impresora', required=True, domain="[('is_3d_printer', '=', True)]")
    lot_id = fields.Many2one(
        'stock.production.lot', string='Carrete',
        domain="[('is_spool', '=', True), ('spool_remaining_g', '>', 0)]",
        help='Vacío = desmontar el carrete actual.')

    def action_confirm(self):
        self.ensure_one()
        self.workcenter_id._mount_lot(self.lot_id)
        return {'type': 'ir.actions.act_window_close'}
