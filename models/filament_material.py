# -*- coding: utf-8 -*-
from odoo import fields, models


class FilamentMaterial(models.Model):
    _name = 'imago.filament.material'
    _description = 'Material de filamento 3D'
    _order = 'sequence, name'

    name = fields.Char(string='Material', required=True)
    code = fields.Char(string='Código', help='Abreviatura usada en el nombre del carrete: PLA, ABS…')
    active = fields.Boolean(string='Activo', default=True)
    sequence = fields.Integer(string='Secuencia', default=10)
    notes = fields.Text(string='Notas', help='Temperatura, cámara cerrada, secado, etc.')

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Ya existe un material con ese nombre.'),
    ]
