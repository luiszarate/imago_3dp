# -*- coding: utf-8 -*-
from odoo import fields, models


class PrintPurpose(models.Model):
    _name = 'imago.print.purpose'
    _description = 'Propósito de impresión 3D'
    _order = 'sequence, name'

    name = fields.Char(string='Propósito', required=True)
    active = fields.Boolean(string='Activo', default=True)
    sequence = fields.Integer(string='Secuencia', default=10)
