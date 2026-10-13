# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.tools import float_compare


class JobStartWizard(models.TransientModel):
    _name = 'imago.print.job.start.wizard'
    _description = 'Iniciar intento de impresión 3D'

    request_id = fields.Many2one('imago.print.request', string='Solicitud', required=True, ondelete='cascade')
    filament_product_id = fields.Many2one(related='request_id.filament_product_id')
    allow_substitute = fields.Boolean(related='request_id.allow_substitute')
    workcenter_id = fields.Many2one(
        'mrp.workcenter', string='Impresora', required=True,
        domain="[('is_3d_printer', '=', True), ('out_of_service', '=', False)]")
    allowed_lot_ids = fields.Many2many(
        'stock.production.lot', string='Carretes permitidos', compute='_compute_allowed_lot_ids')
    lot_ids = fields.Many2many(
        'stock.production.lot', 'imago_job_start_wizard_lot_rel', 'wizard_id', 'lot_id',
        string='Carretes', domain="[('id', 'in', allowed_lot_ids)]")
    pieces_planned = fields.Integer(string='Piezas planeadas')
    est_grams = fields.Float(string='Gramos estimados')
    est_minutes = fields.Integer(string='Minutos estimados')
    warning_text = fields.Text(string='Advertencias', compute='_compute_warning_text')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        request = self.env['imago.print.request'].browse(res.get('request_id'))
        if not request:
            return res
        workcenter = request.planned_workcenter_id
        res.update({
            'workcenter_id': res.get('workcenter_id') or workcenter.id,
            'pieces_planned': res.get('pieces_planned') or request.pieces_pending or request.qty_pieces,
            'est_grams': res.get('est_grams') or request.est_grams,
            'est_minutes': res.get('est_minutes') or request.est_print_minutes,
        })
        lot = workcenter.mounted_lot_id
        if lot and not res.get('lot_ids') and lot in self._allowed_lots(request):
            res['lot_ids'] = [(6, 0, lot.ids)]
        return res

    @api.model
    def _allowed_lots(self, request):
        domain = [
            ('is_spool', '=', True),
            ('spool_remaining_g', '>', 0),
            ('company_id', '=', request.company_id.id),
        ]
        if not request.allow_substitute:
            domain.append(('product_id', '=', request.filament_product_id.id))
        return self.env['stock.production.lot'].search(domain)

    @api.depends('request_id')
    def _compute_allowed_lot_ids(self):
        for wizard in self:
            wizard.allowed_lot_ids = self._allowed_lots(wizard.request_id) if wizard.request_id else False

    @api.onchange('workcenter_id')
    def _onchange_workcenter_id(self):
        lot = self.workcenter_id.mounted_lot_id
        if lot and lot in self.allowed_lot_ids and lot not in self.lot_ids:
            self.lot_ids = [(6, 0, lot.ids)]

    @api.depends('lot_ids', 'est_grams', 'workcenter_id')
    def _compute_warning_text(self):
        for wizard in self:
            warnings = []
            available = sum(wizard.lot_ids.mapped('spool_remaining_g'))
            if wizard.lot_ids and float_compare(available, wizard.est_grams, precision_digits=2) < 0:
                warnings.append(_(
                    'Los carretes seleccionados tienen %(available).1f g y el estimado es %(est).1f g.',
                    available=available, est=wizard.est_grams))
            printer = wizard.workcenter_id
            if printer.printer_status == 'printing':
                warnings.append(_('La impresora está ocupada con %s.') % printer.current_workorder_id.display_name)
            material = wizard.request_id.filament_product_id.filament_material_id
            if printer.allowed_material_ids and material and material not in printer.allowed_material_ids:
                warnings.append(_('La impresora no tiene %s entre sus materiales compatibles.') % material.name)
            wizard.warning_text = '\n'.join(warnings) or False

    def action_start(self):
        self.ensure_one()
        self.request_id._start_job(
            self.workcenter_id, self.lot_ids, self.pieces_planned,
            est_grams=self.est_grams, est_minutes=self.est_minutes)
        return {'type': 'ir.actions.act_window_close'}
