# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_filament = fields.Boolean(string='Es filamento 3D')
    filament_material_id = fields.Many2one('imago.filament.material', string='Material')
    filament_color = fields.Char(string='Color')
    filament_diameter = fields.Selection(
        [('1.75', '1.75 mm'), ('2.85', '2.85 mm')], string='Diámetro', default='1.75')
    spool_nominal_g = fields.Float(
        string='Gramos por carrete', default=1000.0,
        help='Gramos netos de filamento en un carrete nuevo.')
    spool_tare_g = fields.Float(
        string='Tara del carrete (g)', default=0.0,
        help='Peso del carrete vacío; depende de la marca.')

    @api.constrains('is_filament', 'type', 'tracking', 'uom_id', 'uom_po_id', 'filament_material_id', 'filament_color')
    def _check_filament_setup(self):
        weight_categ = self.env.ref('uom.product_uom_categ_kgm')
        gram = self.env.ref('uom.product_uom_gram')
        for template in self.filtered('is_filament'):
            if template.type != 'product':
                raise ValidationError(_('El filamento "%s" debe ser un producto almacenable.') % template.display_name)
            if template.tracking != 'lot':
                raise ValidationError(_('El filamento "%s" debe tener seguimiento por lote (carrete).') % template.display_name)
            if template.uom_id != gram:
                raise ValidationError(_('La unidad de medida de stock del filamento "%s" debe ser el gramo (g).')
                                      % template.display_name)
            if template.uom_po_id.category_id != weight_categ:
                raise ValidationError(_('La unidad de compra del filamento "%s" debe ser de peso (p. ej. kg).')
                                      % template.display_name)
            if not template.filament_material_id or not template.filament_color:
                raise ValidationError(_('Indica el material y el color del filamento "%s".') % template.display_name)

    @api.onchange('is_filament')
    def _onchange_is_filament(self):
        if not self.is_filament:
            return
        self.type = 'product'
        self.tracking = 'lot'
        self.uom_id = self.env.ref('uom.product_uom_gram')
        self.uom_po_id = self.env.ref('uom.product_uom_kgm')

    @api.onchange('uom_id')
    def _onchange_uom_id(self):
        # The standard onchange copies uom_id into uom_po_id; filaments are bought in kg.
        res = super()._onchange_uom_id()
        if self.is_filament and self.uom_id == self.env.ref('uom.product_uom_gram'):
            self.uom_po_id = self.env.ref('uom.product_uom_kgm')
        return res
