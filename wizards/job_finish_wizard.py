# -*- coding: utf-8 -*-
from datetime import timedelta

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
    print_minutes = fields.Integer(
        string='Minutos reales de impresión',
        help='Se prellenan con lo que reportó la impresora (o con el tiempo desde el inicio). Corrígelos si la '
             'impresión terminó antes de cerrar el intento: la ocupación de la impresora usa este valor.')
    print_date_start = fields.Datetime(string='Inicio de impresión', compute='_compute_print_date_start')
    print_date_end = fields.Datetime(string='Fin real de impresión',
                                     help='Se calcula con los minutos; si la cambias, se recalculan los minutos.')
    cancel_request = fields.Boolean(string='Cancelar la solicitud al terminar')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        job = self.env['imago.print.job'].browse(res.get('job_id'))
        if not job:
            return res
        result = res.get('result') or 'ok'
        res['pieces_ok'] = job.pieces_planned if result == 'ok' else 0
        res['print_minutes'] = job._default_print_minutes()
        lots = job.consumption_ids.mapped('lot_id')
        single = len(lots) == 1 and result != 'cancelled'
        res['line_ids'] = [
            (0, 0, {'lot_id': lot.id, 'grams': job.est_grams if single else 0.0}) for lot in lots
        ]
        return res

    @api.depends('job_id')
    def _compute_print_date_start(self):
        for wizard in self:
            wizard.print_date_start = wizard.job_id.date_start

    @api.onchange('print_minutes', 'job_id')
    def _onchange_print_minutes(self):
        start = self.job_id.date_start
        self.print_date_end = start + timedelta(minutes=self.print_minutes) if start and self.print_minutes else False

    @api.onchange('print_date_end')
    def _onchange_print_date_end(self):
        start, end = self.job_id.date_start, self.print_date_end
        if start and end and end > start:
            self.print_minutes = max(round((end - start).total_seconds() / 60.0), 1)

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
            labor_minutes=self.labor_minutes, cancelling=self.cancel_request, print_minutes=self.print_minutes)
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
