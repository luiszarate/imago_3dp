# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    print3d_product_id = fields.Many2one(
        related='company_id.print3d_product_id', readonly=False)
    print3d_location_id = fields.Many2one(
        related='company_id.print3d_location_id', readonly=False)
    print3d_default_operator_id = fields.Many2one(
        related='company_id.print3d_default_operator_id', readonly=False)
    print3d_low_spool_g = fields.Float(
        related='company_id.print3d_low_spool_g', readonly=False)
    print3d_labor_workcenter_id = fields.Many2one(
        related='company_id.print3d_labor_workcenter_id', readonly=False)
    print3d_telemetry_stale_s = fields.Integer(
        related='company_id.print3d_telemetry_stale_s', readonly=False)
    print3d_offline_alert_min = fields.Integer(
        related='company_id.print3d_offline_alert_min', readonly=False)
    print3d_finished_alert_min = fields.Integer(
        related='company_id.print3d_finished_alert_min', readonly=False)
