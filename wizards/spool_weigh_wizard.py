# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class SpoolWeighWizard(models.TransientModel):
    _name = 'imago.spool.weigh.wizard'
    _description = 'Pesar carrete de filamento'

    lot_id = fields.Many2one(
        'stock.production.lot', string='Carrete', required=True, domain="[('is_spool', '=', True)]")
    gross_weight_g = fields.Float(string='Peso en báscula (g)')
    tare_g = fields.Float(string='Tara del carrete (g)')
    net_g = fields.Float(string='Filamento neto (g)', compute='_compute_net')
    current_g = fields.Float(related='lot_id.spool_remaining_g', string='En sistema (g)')
    diff_g = fields.Float(string='Diferencia (g)', compute='_compute_net')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        lot = self.env['stock.production.lot'].browse(res.get('lot_id'))
        if lot and 'default_tare_g' not in self.env.context:
            res['tare_g'] = lot.product_id.spool_tare_g
        return res

    @api.onchange('lot_id')
    def _onchange_lot_id(self):
        self.tare_g = self.lot_id.product_id.spool_tare_g

    @api.depends('gross_weight_g', 'tare_g', 'current_g')
    def _compute_net(self):
        for wizard in self:
            wizard.net_g = wizard.gross_weight_g - wizard.tare_g
            wizard.diff_g = wizard.net_g - wizard.current_g

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group('imago_3dp.group_print_operator'):
            raise AccessError(_('Solo el operador de impresión 3D puede pesar carretes.'))
        if self.net_g < 0:
            raise UserError(_('El peso neto no puede ser negativo: revisa el peso en báscula y la tara.'))
        self.lot_id._spool_set_quantity(self.net_g, _('Pesaje de carrete'))
        self.lot_id._spool_notify_low()
        return {'type': 'ir.actions.act_window_close'}
