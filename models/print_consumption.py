# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero

CONSUMPTION_SOURCES = [
    ('development', 'Desarrollo'),
    ('production', 'Producción'),
]


class PrintConsumption(models.Model):
    _name = 'imago.print.consumption'
    _description = 'Consumo de filamento 3D'
    _order = 'date desc, id desc'
    _rec_name = 'lot_id'

    job_id = fields.Many2one(
        'imago.print.job', string='Intento', ondelete='cascade', index=True)
    request_id = fields.Many2one(
        related='job_id.request_id', string='Solicitud', store=True)
    workorder_id = fields.Many2one(
        'mrp.workorder', string='Orden de trabajo', index=True, ondelete='set null')
    production_id = fields.Many2one(
        'mrp.production', string='Orden de fabricación',
        compute='_compute_links', store=True)
    lot_id = fields.Many2one(
        'stock.production.lot', string='Carrete', required=True,
        domain="[('is_spool', '=', True)]")
    product_id = fields.Many2one(
        related='lot_id.product_id', string='Filamento', store=True)
    material_id = fields.Many2one(
        related='product_id.filament_material_id', string='Material', store=True)
    purpose_id = fields.Many2one(
        related='job_id.request_id.purpose_id', string='Propósito', store=True)
    workcenter_id = fields.Many2one(
        'mrp.workcenter', string='Impresora', compute='_compute_links', store=True)
    source = fields.Selection(
        CONSUMPTION_SOURCES, string='Origen', compute='_compute_links', store=True)
    company_id = fields.Many2one(
        'res.company', string='Compañía', compute='_compute_links', store=True)
    grams = fields.Float(string='Gramos', digits='Product Unit of Measure')
    stock_move_id = fields.Many2one('stock.move', string='Movimiento de stock', readonly=True, copy=False)
    date = fields.Datetime(string='Fecha', default=fields.Datetime.now, required=True)

    @api.depends('job_id.workcenter_id', 'job_id.request_id.production_id', 'job_id.company_id',
                 'workorder_id.workcenter_id', 'workorder_id.production_id', 'workorder_id.company_id')
    def _compute_links(self):
        for consumption in self:
            job = consumption.job_id
            workorder = consumption.workorder_id
            consumption.source = 'development' if job else 'production'
            consumption.workcenter_id = job.workcenter_id or workorder.workcenter_id
            # The attempt's own WO pins the MO (a reopened request may get a new MO).
            consumption.production_id = workorder.production_id or job.request_id.production_id
            consumption.company_id = job.company_id or workorder.company_id or self.env.company

    def write(self, vals):
        locked = {'grams', 'lot_id', 'job_id', 'workorder_id'} & set(vals)
        if locked and self.filtered('stock_move_id'):
            raise UserError(_('El consumo ya generó su movimiento de stock y no se puede modificar; '
                              'corrige el carrete con [Pesar carrete].'))
        return super().write(vals)

    def unlink(self):
        if self.filtered('stock_move_id'):
            raise UserError(_('No se puede borrar un consumo que ya generó su movimiento de stock.'))
        return super().unlink()

    @api.constrains('job_id', 'workorder_id', 'grams')
    def _check_consumption(self):
        for consumption in self:
            if not consumption.job_id and not consumption.workorder_id:
                raise ValidationError(_('El consumo debe estar ligado a un intento o a una orden de trabajo.'))
            if consumption.grams < 0:
                raise ValidationError(_('Los gramos consumidos no pueden ser negativos.'))

    # ------------------------------------------------------------------
    # Stock
    # ------------------------------------------------------------------
    def _post_stock_move(self):
        """Create and validate the stock move that removes the grams from the spool."""
        for consumption in self.filtered(lambda c: not c.stock_move_id):
            consumption._check_can_post()
            location = consumption.company_id._print3d_get_location()
            move = self.env['stock.move'].create(consumption._prepare_stock_move_vals(location))
            move._action_confirm(merge=False)
            consumption._create_move_lines(move)
            move._action_done()
            if move.state != 'done':
                raise UserError(_('No se pudo validar el movimiento de filamento del carrete %s.')
                                % consumption.lot_id.name)
            consumption.stock_move_id = move
            consumption.lot_id._spool_mark_opened()
        return True

    def _check_can_post(self):
        self.ensure_one()
        lot = self.lot_id
        rounding = lot.product_id.uom_id.rounding
        if float_compare(self.grams, 0.0, precision_rounding=rounding) <= 0:
            raise UserError(_('Indica los gramos consumidos del carrete %s.') % lot.name)
        available = lot._spool_available_g()
        if float_compare(self.grams, available, precision_rounding=rounding) > 0:
            raise UserError(_(
                'El carrete %(lot)s solo tiene %(available).1f g disponibles en la ubicación 3D y '
                'se intentan consumir %(grams).1f g. Usa [Pesar carrete] para corregir el inventario.',
                lot=lot.name, available=max(available, 0.0), grams=self.grams))

    def _prepare_stock_move_vals(self, location):
        """Development consumptions are raw moves of the request MO (needed so that
        the MO can be marked as done). Production consumptions (7.7) are standalone
        moves so they never alter the BOM consumption check of the production MO."""
        self.ensure_one()
        product = self.product_id
        if self.job_id and self.production_id:
            vals = self.production_id._get_move_raw_values(product, self.grams, product.uom_id)
            vals.update({
                'name': _('Filamento %s – %s') % (self.lot_id.name, self.job_id.name),
                'origin': self.job_id.request_id.name,
                'location_id': location.id,
            })
        else:
            production = self.production_id
            vals = {
                'name': _('Filamento %s – %s') % (self.lot_id.name, self.workorder_id.display_name),
                'origin': production.name if production else self.workorder_id.name,
                'product_id': product.id,
                'product_uom': product.uom_id.id,
                'product_uom_qty': self.grams,
                'location_id': location.id,
                'location_dest_id': product.with_company(self.company_id).property_stock_production.id,
                'company_id': self.company_id.id,
                'group_id': production.procurement_group_id.id if production else False,
            }
        vals['print_consumption_id'] = self.id
        return vals

    def _create_move_lines(self, move):
        self.ensure_one()
        rounding = move.product_uom.rounding
        remaining = self.grams
        quants = self.lot_id._spool_quants().sorted(lambda q: -q.quantity)
        for quant in quants:
            free = quant.quantity - quant.reserved_quantity
            if float_compare(free, 0.0, precision_rounding=rounding) <= 0:
                continue
            qty = min(remaining, free)
            self.env['stock.move.line'].create({
                'move_id': move.id,
                'product_id': move.product_id.id,
                'product_uom_id': move.product_uom.id,
                'location_id': quant.location_id.id,
                'location_dest_id': move.location_dest_id.id,
                'lot_id': self.lot_id.id,
                'qty_done': qty,
                'company_id': move.company_id.id,
            })
            remaining -= qty
            if float_is_zero(remaining, precision_rounding=rounding):
                break
        if not float_is_zero(remaining, precision_rounding=rounding):
            raise UserError(_('El carrete %s no tiene existencia suficiente en la ubicación 3D.')
                            % self.lot_id.name)
