# -*- coding: utf-8 -*-
import re
import unicodedata

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare, float_is_zero, float_round, html_escape

SPOOL_STATES = [
    ('new', 'Nuevo'),
    ('open', 'Abierto'),
    ('low', 'Casi vacío'),
    ('empty', 'Vacío'),
]


def _slug(text, size):
    """ASCII, alphanumeric, upper-case abbreviation: 'Negro' -> 'NEG'."""
    normalized = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^A-Za-z0-9]', '', normalized).upper()[:size]


class StockProductionLot(models.Model):
    _inherit = 'stock.production.lot'

    is_spool = fields.Boolean(
        string='Es carrete', related='product_id.is_filament', store=True)
    filament_material_id = fields.Many2one(
        'imago.filament.material', string='Material',
        related='product_id.filament_material_id', store=True)
    filament_color = fields.Char(string='Color', related='product_id.filament_color')
    spool_remaining_g = fields.Float(
        string='Gramos restantes', compute='_compute_spool_values', store=True,
        digits='Product Unit of Measure',
        help='Existencia del carrete en la ubicación de filamento 3D (y sus sububicaciones).')
    spool_remaining_pct = fields.Float(
        string='% restante', compute='_compute_spool_values', store=True, group_operator='avg')
    spool_state = fields.Selection(
        SPOOL_STATES, string='Estado del carrete', compute='_compute_spool_values', store=True)
    mounted_workcenter_id = fields.Many2one(
        'mrp.workcenter', string='Impresora montada', compute='_compute_mounted_workcenter')
    opened_date = fields.Datetime(string='Fecha de apertura', readonly=True, copy=False)

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    def _spool_quants(self):
        """Quants of this lot inside the 3D filament location (child_of)."""
        self.ensure_one()
        location = self.company_id.print3d_location_id
        if location:
            return self.quant_ids.filtered(
                lambda q: q.location_id.parent_path.startswith(location.parent_path))
        return self.quant_ids.filtered(lambda q: q.location_id.usage == 'internal')

    @api.depends('is_spool', 'quant_ids.quantity', 'quant_ids.location_id', 'opened_date',
                 'product_id.spool_nominal_g', 'company_id.print3d_location_id',
                 'company_id.print3d_low_spool_g')
    def _compute_spool_values(self):
        for lot in self:
            if not lot.is_spool:
                lot.spool_remaining_g = 0.0
                lot.spool_remaining_pct = 0.0
                lot.spool_state = False
                continue
            rounding = lot.product_id.uom_id.rounding
            remaining = float_round(sum(lot._spool_quants().mapped('quantity')), precision_rounding=rounding)
            nominal = lot.product_id.spool_nominal_g
            lot.spool_remaining_g = remaining
            lot.spool_remaining_pct = max(remaining, 0.0) / nominal * 100.0 if nominal else 0.0
            lot.spool_state = lot._spool_state_for(remaining)

    def _spool_state_for(self, remaining):
        self.ensure_one()
        rounding = self.product_id.uom_id.rounding
        if float_compare(remaining, 0.0, precision_rounding=rounding) <= 0:
            return 'empty'
        if float_compare(remaining, self.company_id.print3d_low_spool_g, precision_rounding=rounding) <= 0:
            return 'low'
        return 'open' if self.opened_date else 'new'

    def _compute_mounted_workcenter(self):
        real_ids = [lot_id for lot_id in self.ids if isinstance(lot_id, int)]
        workcenters = self.env['mrp.workcenter'].sudo().search([('mounted_lot_id', 'in', real_ids)])
        by_lot = {wc.mounted_lot_id.id: wc.id for wc in workcenters}
        for lot in self:
            lot.mounted_workcenter_id = by_lot.get(lot.id, False)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    def _spool_generate_name(self, product):
        """<MATERIAL>-<COLOR3>-<seq>, e.g. ABS-NEG-0007."""
        material = product.filament_material_id
        material_code = _slug(material.code or material.name, 6) or 'FIL'
        color_code = _slug(product.filament_color, 3) or 'XXX'
        sequence = self.env['ir.sequence'].sudo().next_by_code('imago.spool')
        return '%s-%s-%s' % (material_code, color_code, sequence)

    def _spool_available_g(self):
        """Grams that can still be consumed (quantity minus reservations) in the 3D location."""
        self.ensure_one()
        quants = self._spool_quants()
        return sum(quants.mapped('quantity')) - sum(quants.mapped('reserved_quantity'))

    def _spool_mark_opened(self):
        self.filtered(lambda lot: not lot.opened_date).write({'opened_date': fields.Datetime.now()})

    def _spool_set_quantity(self, new_qty, reason):
        """Inventory adjustment of this spool to ``new_qty`` grams in the 3D location.

        Uses the standard Odoo 14 mechanism (stock.inventory). ``action_validate``
        checks ``user_has_groups('stock.group_stock_manager')`` (not bypassed by
        ``sudo()``), so the adjustment runs as the superuser once the caller (3D
        operator) has been authorised by the wizard/button.
        """
        self.ensure_one()
        if not self.is_spool:
            raise UserError(_('El lote %s no es un carrete de filamento.') % self.name)
        if new_qty < 0:
            raise UserError(_('La cantidad del carrete no puede ser negativa.'))
        location = self.company_id._print3d_get_location()
        previous = self.spool_remaining_g
        Inventory = self.env['stock.inventory'].with_user(SUPERUSER_ID)
        inventory = Inventory.create({
            'name': _('%s: %s') % (reason, self.name),
            'company_id': self.company_id.id,
            'location_ids': [(6, 0, location.ids)],
            'product_ids': [(6, 0, self.product_id.ids)],
            'start_empty': True,
        })
        inventory.action_start()
        quants = self.sudo()._spool_quants().filtered(lambda q: q.location_id.usage == 'internal')
        target_locations = quants.mapped('location_id') or location
        line_vals = []
        for index, target in enumerate(target_locations):
            line_vals.append({
                'inventory_id': inventory.id,
                'product_id': self.product_id.id,
                'product_uom_id': self.product_id.uom_id.id,
                'prod_lot_id': self.id,
                'location_id': target.id,
                'product_qty': new_qty if index == 0 else 0.0,
            })
        self.env['stock.inventory.line'].with_user(SUPERUSER_ID).create(line_vals)
        inventory.action_validate()
        if inventory.state != 'done':
            raise UserError(_('No se pudo validar el ajuste de inventario del carrete %s.') % self.name)
        diff = new_qty - previous
        self.message_post(body=_(
            '%(reason)s: el carrete pasó de %(before).1f g a %(after).1f g (diferencia %(diff)+.1f g).',
            reason=html_escape(reason), before=previous, after=new_qty, diff=diff))
        return diff

    def _spool_notify_low(self, request=False):
        """Warn the operator when a spool is at or below the low threshold."""
        activity_type = self.env.ref('imago_3dp.mail_activity_low_spool', raise_if_not_found=False)
        for lot in self.filtered(lambda l: l.is_spool and l.spool_state in ('low', 'empty')):
            body = _('El carrete %(lot)s quedó con %(grams).1f g (casi vacío).',
                     lot=html_escape(lot.name), grams=lot.spool_remaining_g)
            if request:
                request.message_post(body=body)
            user = (request and request.operator_id) or lot.company_id.print3d_default_operator_id or self.env.user
            pending = lot.activity_ids.filtered(lambda a: a.activity_type_id == activity_type)
            if activity_type and not pending:
                lot.activity_schedule(
                    'imago_3dp.mail_activity_low_spool',
                    summary=_('Carrete %s casi vacío') % lot.name,
                    note=body,
                    user_id=user.id)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_open_weigh_wizard(self):
        self.ensure_one()
        return {
            'name': _('Pesar carrete'),
            'type': 'ir.actions.act_window',
            'res_model': 'imago.spool.weigh.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_lot_id': self.id},
        }

    def action_mark_empty(self):
        if not self.env.su and not self.env.user.has_group('imago_3dp.group_print_operator'):
            raise AccessError(_('Solo el operador de impresión 3D puede marcar carretes como agotados.'))
        for lot in self.filtered('is_spool'):
            if not float_is_zero(lot.spool_remaining_g, precision_rounding=lot.product_id.uom_id.rounding):
                lot._spool_set_quantity(0.0, _('Carrete agotado'))
            # mrp.group_mrp_user cannot write work centers: narrow superuser write.
            mounted = self.env['mrp.workcenter'].sudo().search([('mounted_lot_id', '=', lot.id)])
            mounted.write({'mounted_lot_id': False})
        return True
