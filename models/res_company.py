# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError

DEFAULT_LOW_SPOOL_G = 150.0


class ResCompany(models.Model):
    _inherit = 'res.company'

    print3d_product_id = fields.Many2one(
        'product.product', string='Producto genérico de impresión 3D',
        help='Producto de las órdenes de fabricación que se generan por cada solicitud.')
    print3d_location_id = fields.Many2one(
        'stock.location', string='Ubicación de filamento 3D',
        domain="[('usage', '=', 'internal')]",
        help='Ubicación interna donde viven los carretes (p. ej. WH/Stock/3DP).')
    print3d_default_operator_id = fields.Many2one(
        'res.users', string='Operador de impresión por defecto')
    print3d_low_spool_g = fields.Float(
        string='Umbral de carrete casi vacío (g)', default=DEFAULT_LOW_SPOOL_G)
    print3d_labor_workcenter_id = fields.Many2one(
        'mrp.workcenter', string='Centro de mano de obra 3D',
        help='Centro de trabajo donde se registra la WO [LAB] de preparación y post-proceso.')

    def _print3d_get_location(self):
        """Return the 3D filament location or raise a clear configuration error."""
        self.ensure_one()
        if not self.print3d_location_id:
            raise UserError(_(
                'Configura la ubicación de filamento 3D en Ajustes → Manufactura → Impresión 3D.'))
        return self.print3d_location_id

    def _print3d_get_product(self):
        """Return the generic product used for the print MOs."""
        self.ensure_one()
        product = self.print3d_product_id or self.env.ref(
            'imago_3dp.product_print3d_prototype', raise_if_not_found=False)
        if not product:
            raise UserError(_(
                'Configura el producto genérico de impresión 3D en Ajustes → Manufactura → Impresión 3D.'))
        return product

    def _print3d_get_labor_workcenter(self):
        self.ensure_one()
        if not self.print3d_labor_workcenter_id:
            raise UserError(_(
                'Configura el centro de trabajo de mano de obra 3D en Ajustes → Manufactura → Impresión 3D '
                'para registrar minutos de mano de obra.'))
        return self.print3d_labor_workcenter_id
