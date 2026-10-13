# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class WorkorderFilamentWizard(models.TransientModel):
    _name = 'imago.workorder.filament.wizard'
    _description = 'Registrar filamento en una orden de trabajo'

    workorder_id = fields.Many2one('mrp.workorder', string='Orden de trabajo', required=True, ondelete='cascade')
    line_ids = fields.One2many('imago.workorder.filament.wizard.line', 'wizard_id', string='Consumo por carrete')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        workorder = self.env['mrp.workorder'].browse(res.get('workorder_id'))
        lot = workorder.workcenter_id.mounted_lot_id
        if lot and 'line_ids' in fields_list and not res.get('line_ids'):
            res['line_ids'] = [(0, 0, {'lot_id': lot.id, 'grams': 0.0})]
        return res

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group('imago_3dp.group_print_operator'):
            raise AccessError(_('Solo el operador de impresión 3D puede registrar filamento.'))
        workorder = self.workorder_id
        if not workorder.workcenter_id.is_3d_printer:
            raise UserError(_('La orden de trabajo %s no está en una impresora 3D.') % workorder.display_name)
        if workorder.production_id.print_request_id:
            raise UserError(_('La orden de trabajo %s pertenece a una solicitud de impresión: registra el '
                              'filamento con [Terminar intento].') % workorder.display_name)
        if workorder.state == 'cancel':
            raise UserError(_('La orden de trabajo %s está cancelada.') % workorder.display_name)
        lines = self.line_ids.filtered(lambda line: line.grams > 0)
        if not lines:
            raise UserError(_('Captura los gramos consumidos en al menos un carrete.'))
        consumptions = self.env['imago.print.consumption'].create([{
            'workorder_id': workorder.id,
            'lot_id': line.lot_id.id,
            'grams': line.grams,
        } for line in lines])
        consumptions._post_stock_move()
        consumptions.mapped('lot_id')._spool_notify_low()
        return {'type': 'ir.actions.act_window_close'}


class WorkorderFilamentWizardLine(models.TransientModel):
    _name = 'imago.workorder.filament.wizard.line'
    _description = 'Línea de filamento de una orden de trabajo'

    wizard_id = fields.Many2one('imago.workorder.filament.wizard', required=True, ondelete='cascade')
    lot_id = fields.Many2one(
        'stock.production.lot', string='Carrete', required=True,
        domain="[('is_spool', '=', True), ('spool_remaining_g', '>', 0)]")
    available_g = fields.Float(related='lot_id.spool_remaining_g', string='Disponible (g)')
    grams = fields.Float(string='Gramos consumidos')
