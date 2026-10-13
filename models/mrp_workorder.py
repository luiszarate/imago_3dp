# -*- coding: utf-8 -*-
from odoo import _, fields, models


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    is_3d_printer = fields.Boolean(related='workcenter_id.is_3d_printer', string='En impresora 3D')
    is_print_request_wo = fields.Boolean(
        string='WO de solicitud 3D', compute='_compute_is_print_request_wo')
    print_consumption_ids = fields.One2many(
        'imago.print.consumption', 'workorder_id', string='Consumo de filamento')

    def _compute_is_print_request_wo(self):
        for workorder in self:
            workorder.is_print_request_wo = bool(workorder.production_id.print_request_id)

    def action_open_filament_wizard(self):
        self.ensure_one()
        return {
            'name': _('Registrar filamento'),
            'type': 'ir.actions.act_window',
            'res_model': 'imago.workorder.filament.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_workorder_id': self.id},
        }
