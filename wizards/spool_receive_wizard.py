# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_round


class SpoolReceiveWizard(models.TransientModel):
    _name = 'imago.spool.receive.wizard'
    _description = 'Generar carretes en una recepción'

    picking_id = fields.Many2one('stock.picking', string='Recepción', required=True, ondelete='cascade')
    line_ids = fields.One2many('imago.spool.receive.wizard.line', 'wizard_id', string='Filamentos')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        picking = self.env['stock.picking'].browse(res.get('picking_id'))
        if not picking or 'line_ids' not in fields_list:
            return res
        lines = []
        for move in picking.move_lines.filtered(
                lambda m: m.product_id.is_filament and m.state not in ('done', 'cancel')):
            product = move.product_id
            qty_g = move.product_uom._compute_quantity(move.product_uom_qty, product.uom_id)
            nominal = product.spool_nominal_g or 1000.0
            lines.append((0, 0, {
                'move_id': move.id,
                'spool_count': max(int(float_round(qty_g / nominal, precision_digits=0)), 1),
                'grams_per_spool': nominal,
            }))
        res['line_ids'] = lines
        return res

    def action_generate(self):
        self.ensure_one()
        if not self.env.user.has_group('imago_3dp.group_print_operator'):
            raise AccessError(_('Solo el operador de impresión 3D puede generar carretes.'))
        picking = self.picking_id
        if picking.state in ('done', 'cancel'):
            raise UserError(_('La recepción %s ya está cerrada.') % picking.name)
        if not self.line_ids:
            raise UserError(_('La recepción no tiene líneas de filamento pendientes.'))
        location = picking.company_id._print3d_get_location()
        for line in self.line_ids:
            line._generate_spools(location)
        return {'type': 'ir.actions.act_window_close'}


class SpoolReceiveWizardLine(models.TransientModel):
    _name = 'imago.spool.receive.wizard.line'
    _description = 'Filamento a recibir en carretes'

    wizard_id = fields.Many2one('imago.spool.receive.wizard', required=True, ondelete='cascade')
    move_id = fields.Many2one('stock.move', string='Movimiento', required=True)
    product_id = fields.Many2one(related='move_id.product_id', string='Filamento')
    qty_g = fields.Float(string='Cantidad recibida (g)', compute='_compute_qty_g')
    spool_count = fields.Integer(string='Nº de carretes')
    grams_per_spool = fields.Float(string='Gramos por carrete')

    @api.depends('move_id')
    def _compute_qty_g(self):
        for line in self:
            move = line.move_id
            line.qty_g = move.product_uom._compute_quantity(move.product_uom_qty, move.product_id.uom_id) \
                if move else 0.0

    def _generate_spools(self, location):
        self.ensure_one()
        move = self.move_id
        product = move.product_id
        if self.spool_count <= 0 or self.grams_per_spool <= 0:
            raise UserError(_('Indica el número de carretes y los gramos por carrete de %s.') % product.display_name)
        if move.move_line_ids.filtered(lambda ml: ml.lot_id):
            raise UserError(_('Ya hay lotes asignados a %s en esta recepción.') % product.display_name)
        Lot = self.env['stock.production.lot']
        lots = Lot.create([{
            'name': Lot._spool_generate_name(product),
            'product_id': product.id,
            'company_id': move.company_id.id,
        } for _index in range(self.spool_count)])
        self.env['stock.move.line'].create([{
            'move_id': move.id,
            'picking_id': move.picking_id.id,
            'product_id': product.id,
            'product_uom_id': product.uom_id.id,
            'location_id': move.location_id.id,
            'location_dest_id': location.id,
            'lot_id': lot.id,
            'qty_done': self.grams_per_spool,
            'company_id': move.company_id.id,
        } for lot in lots])
        return lots
