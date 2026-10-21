# -*- coding: utf-8 -*-
from odoo import api, fields, models

from ..models.print_job import FAILURE_REASONS, RESULTS_REQUIRING_REASON
from .job_finish_wizard import FINISH_RESULTS

# Percentages are shown with 2 decimals (3 × 33.33 = 99.99): a total this close to
# 100 % is normalized instead of rejected.
SHARE_ROUNDING_SLACK_PCT = 0.05


class BatchFinishWizard(models.TransientModel):
    _name = 'imago.print.batch.finish.wizard'
    _description = 'Terminar impresión combinada 3D'

    batch_id = fields.Many2one('imago.print.batch', string='Impresión combinada', required=True,
                               ondelete='cascade')
    workcenter_id = fields.Many2one(related='batch_id.workcenter_id')
    plate_result = fields.Selection(FINISH_RESULTS, string='Resultado de la placa', required=True, default='ok')
    failure_reason = fields.Selection(FAILURE_REASONS, string='Causa de falla')
    failure_note = fields.Text(string='Detalle de la falla')
    labor_minutes = fields.Integer(string='Mano de obra (min)',
                                   help='Total de la placa; se reparte entre las solicitudes.')
    lot_line_ids = fields.One2many('imago.print.batch.finish.wizard.lot', 'wizard_id',
                                   string='Consumo por carrete (total de la placa)')
    request_line_ids = fields.One2many('imago.print.batch.finish.wizard.request', 'wizard_id',
                                       string='Resultado por solicitud')
    share_total = fields.Float(string='Suma del reparto (%)', compute='_compute_share_total')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        batch = self.env['imago.print.batch'].browse(res.get('batch_id'))
        if not batch:
            return res
        jobs = batch.job_ids.sorted('id')
        lots = jobs.mapped('consumption_ids.lot_id')
        est_total = sum(jobs.mapped('est_grams'))
        res['lot_line_ids'] = [
            (0, 0, {'lot_id': lot.id, 'grams': est_total if len(lots) == 1 else 0.0}) for lot in lots
        ]
        res['request_line_ids'] = [(0, 0, {
            'job_id': job.id,
            'result': 'ok',
            'pieces_ok': job.pieces_planned,
            'share_pct': job.share * 100.0,
        }) for job in jobs]
        return res

    @api.depends('request_line_ids.share_pct')
    def _compute_share_total(self):
        for wizard in self:
            wizard.share_total = sum(wizard.request_line_ids.mapped('share_pct'))

    @api.onchange('plate_result')
    def _onchange_plate_result(self):
        for line in self.request_line_ids:
            line.result = self.plate_result
            line._onchange_result()

    @api.onchange('failure_reason', 'failure_note')
    def _onchange_failure_reason(self):
        for line in self.request_line_ids.filtered(lambda l: l.result in RESULTS_REQUIRING_REASON + ('cancelled',)):
            line.failure_reason = self.failure_reason
            line.failure_note = self.failure_note

    def action_finish(self):
        self.ensure_one()
        self.batch_id._check_operator()
        lot_lines = [(line.lot_id, line.grams) for line in self.lot_line_ids if line.lot_id]
        total_pct = self.share_total
        scale = total_pct if abs(total_pct - 100.0) <= SHARE_ROUNDING_SLACK_PCT and total_pct else 100.0
        request_lines = [{
            'job': line.job_id,
            'result': line.result,
            'pieces_ok': line.pieces_ok,
            'failure_reason': line.failure_reason,
            'failure_note': line.failure_note,
            'share': line.share_pct / scale,
        } for line in self.request_line_ids]
        self.batch_id._finish_combined(lot_lines, request_lines, labor_minutes=self.labor_minutes)
        return {'type': 'ir.actions.act_window_close'}


class BatchFinishWizardLot(models.TransientModel):
    _name = 'imago.print.batch.finish.wizard.lot'
    _description = 'Consumo por carrete al terminar impresión combinada'

    wizard_id = fields.Many2one('imago.print.batch.finish.wizard', required=True, ondelete='cascade')
    lot_id = fields.Many2one(
        'stock.production.lot', string='Carrete', required=True,
        domain="[('is_spool', '=', True), ('spool_remaining_g', '>', 0)]")
    available_g = fields.Float(related='lot_id.spool_remaining_g', string='Disponible (g)')
    grams = fields.Float(string='Gramos consumidos')


class BatchFinishWizardRequest(models.TransientModel):
    _name = 'imago.print.batch.finish.wizard.request'
    _description = 'Resultado por solicitud al terminar impresión combinada'

    wizard_id = fields.Many2one('imago.print.batch.finish.wizard', required=True, ondelete='cascade')
    job_id = fields.Many2one('imago.print.job', string='Intento', required=True)
    request_id = fields.Many2one(related='job_id.request_id', string='Solicitud')
    pieces_planned = fields.Integer(related='job_id.pieces_planned', string='Piezas planeadas')
    result = fields.Selection(FINISH_RESULTS, string='Resultado', required=True, default='ok')
    pieces_ok = fields.Integer(string='Piezas OK')
    failure_reason = fields.Selection(FAILURE_REASONS, string='Causa de falla')
    failure_note = fields.Text(string='Detalle de la falla')
    share_pct = fields.Float(string='Parte (%)', digits=(16, 2))

    @api.onchange('result')
    def _onchange_result(self):
        if self.result == 'ok':
            self.pieces_ok = self.pieces_planned
        elif self.result in ('failed', 'cancelled'):
            self.pieces_ok = 0
