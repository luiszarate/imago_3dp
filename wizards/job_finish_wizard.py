# -*- coding: utf-8 -*-
from odoo import api, fields, models

from ..models.print_job import FAILURE_REASONS

FINISH_RESULTS = [
    ('ok', 'OK'),
    ('partial', 'Parcial'),
    ('failed', 'Fallido'),
    ('cancelled', 'Cancelado'),
]


class JobFinishWizard(models.TransientModel):
    _name = 'imago.print.job.finish.wizard'
    _description = 'Terminar intento de impresión 3D'

    job_id = fields.Many2one('imago.print.job', string='Intento', required=True, ondelete='cascade')
    request_id = fields.Many2one(related='job_id.request_id')
    pieces_planned = fields.Integer(related='job_id.pieces_planned')
    result = fields.Selection(FINISH_RESULTS, string='Resultado', required=True, default='ok')
    pieces_ok = fields.Integer(string='Piezas OK')
    line_ids = fields.One2many('imago.print.job.finish.wizard.line', 'wizard_id', string='Consumo por carrete')
    failure_reason = fields.Selection(FAILURE_REASONS, string='Causa de falla')
    failure_note = fields.Text(string='Detalle de la falla')
    labor_minutes = fields.Integer(string='Mano de obra (min)', help='Preparación y post-proceso (opcional).')
    cancel_request = fields.Boolean(string='Cancelar la solicitud al terminar')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        job = self.env['imago.print.job'].browse(res.get('job_id'))
        if not job:
            return res
        result = res.get('result') or 'ok'
        res['pieces_ok'] = job.pieces_planned if result == 'ok' else 0
        lots = job.consumption_ids.mapped('lot_id')
        single = len(lots) == 1 and result != 'cancelled'
        res['line_ids'] = [
            (0, 0, {'lot_id': lot.id, 'grams': job.est_grams if single else 0.0}) for lot in lots
        ]
        return res

    @api.onchange('result')
    def _onchange_result(self):
        if self.result == 'ok':
            self.pieces_ok = self.pieces_planned
        elif self.result in ('failed', 'cancelled'):
            self.pieces_ok = 0

    def action_finish(self):
        self.ensure_one()
        self.request_id._check_operator()
        lines = [(line.lot_id, line.grams) for line in self.line_ids if line.lot_id]
        self.job_id._finish(
            self.result, self.pieces_ok, lines,
            failure_reason=self.failure_reason, failure_note=self.failure_note,
            labor_minutes=self.labor_minutes, cancelling=self.cancel_request)
        if self.cancel_request:
            self.request_id._do_cancel()
        return {'type': 'ir.actions.act_window_close'}


class JobFinishWizardLine(models.TransientModel):
    _name = 'imago.print.job.finish.wizard.line'
    _description = 'Consumo por carrete al terminar intento'

    wizard_id = fields.Many2one('imago.print.job.finish.wizard', required=True, ondelete='cascade')
    lot_id = fields.Many2one(
        'stock.production.lot', string='Carrete', required=True,
        domain="[('is_spool', '=', True), ('spool_remaining_g', '>', 0)]")
    available_g = fields.Float(related='lot_id.spool_remaining_g', string='Disponible (g)')
    grams = fields.Float(string='Gramos consumidos')
