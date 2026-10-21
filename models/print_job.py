# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

JOB_RESULTS = [
    ('running', 'En curso'),
    ('ok', 'OK'),
    ('partial', 'Parcial'),
    ('failed', 'Fallido'),
    ('cancelled', 'Cancelado'),
]

FAILURE_REASONS = [
    ('adhesion', 'Adhesión/warping'),
    ('spaghetti', 'Desprendimiento'),
    ('clog', 'Boquilla tapada'),
    ('runout', 'Se acabó el filamento'),
    ('layer_shift', 'Desfase de capas'),
    ('file', 'Archivo/diseño'),
    ('power', 'Corte de energía'),
    ('other', 'Otro'),
]

RESULTS_REQUIRING_REASON = ('partial', 'failed')
# Worst first: the printer indicators of a combined plate use its worst result.
RESULT_SEVERITY = ('running', 'failed', 'partial', 'ok', 'cancelled')
# Set only by imago.print.batch (as superuser, after its own checks).
BATCH_FIELDS = ('batch_id', 'share')


class PrintJob(models.Model):
    _name = 'imago.print.job'
    _description = 'Intento de impresión 3D'
    _order = 'date_start desc, id desc'

    name = fields.Char(string='Intento', compute='_compute_name', store=True)
    request_id = fields.Many2one(
        'imago.print.request', string='Solicitud', required=True, ondelete='cascade', index=True)
    attempt_no = fields.Integer(string='Nº de intento')
    workcenter_id = fields.Many2one(
        'mrp.workcenter', string='Impresora', required=True, domain="[('is_3d_printer', '=', True)]")
    workorder_id = fields.Many2one('mrp.workorder', string='WO [MCH]', readonly=True, copy=False)
    labor_workorder_id = fields.Many2one('mrp.workorder', string='WO [LAB]', readonly=True, copy=False)
    operator_id = fields.Many2one('res.users', string='Operador', default=lambda self: self.env.user)
    pieces_planned = fields.Integer(string='Piezas planeadas')
    pieces_ok = fields.Integer(string='Piezas OK')
    est_grams = fields.Float(string='Gramos estimados')
    est_minutes = fields.Integer(string='Minutos estimados')
    date_start = fields.Datetime(string='Inicio')
    date_end = fields.Datetime(string='Fin')
    duration_minutes = fields.Float(string='Duración (min)', compute='_compute_duration', store=True)
    result = fields.Selection(JOB_RESULTS, string='Resultado', default='running', required=True)
    failure_reason = fields.Selection(FAILURE_REASONS, string='Causa de falla')
    failure_note = fields.Text(string='Detalle de la falla')
    labor_minutes = fields.Integer(string='Mano de obra (min)')
    consumption_ids = fields.One2many('imago.print.consumption', 'job_id', string='Consumo de filamento')
    grams_total = fields.Float(string='Gramos consumidos', compute='_compute_grams_total', store=True)
    failure_count = fields.Integer(
        string='Fallidos', compute='_compute_failure_count', store=True,
        help='1 si el intento falló; sumar para obtener la tasa de fallos.')
    company_id = fields.Many2one(related='request_id.company_id', string='Compañía', store=True)
    purpose_id = fields.Many2one(related='request_id.purpose_id', string='Propósito', store=True)
    # Combined print (SPEC 17): one attempt per request sharing a plate.
    batch_id = fields.Many2one(
        'imago.print.batch', string='Impresión combinada', ondelete='restrict', index=True, readonly=True,
        copy=False)
    share = fields.Float(string='Parte de la placa', digits=(16, 4), default=1.0, readonly=True,
                         help='Fracción de la placa que corresponde a esta solicitud (1 = intento individual).')
    is_batch_lead = fields.Boolean(string='Intento líder', compute='_compute_batch_flags', store=True)
    counts_for_printer = fields.Boolean(
        string='Cuenta para la impresora', compute='_compute_batch_flags', store=True,
        help='Los indicadores por impresora cuentan una impresión combinada una sola vez.')
    printer_result = fields.Selection(
        JOB_RESULTS, string='Resultado de la placa', compute='_compute_printer_result', store=True,
        help='Peor resultado de la impresión combinada (el propio en intentos individuales).')
    printer_failure_reason = fields.Selection(
        FAILURE_REASONS, string='Causa de falla de la placa', compute='_compute_printer_result', store=True)
    allocated_minutes = fields.Float(
        string='Minutos asignados', compute='_compute_allocated_minutes', store=True,
        help='Duración por la parte de la placa de esta solicitud.')

    @api.depends('request_id.name', 'attempt_no')
    def _compute_name(self):
        for job in self:
            job.name = '%s/%s' % (job.request_id.name or '', job.attempt_no or 0)

    @api.depends('date_start', 'date_end')
    def _compute_duration(self):
        for job in self:
            if job.date_start and job.date_end:
                job.duration_minutes = (job.date_end - job.date_start).total_seconds() / 60.0
            else:
                job.duration_minutes = 0.0

    @api.depends('consumption_ids.grams')
    def _compute_grams_total(self):
        for job in self:
            job.grams_total = sum(job.consumption_ids.mapped('grams'))

    @api.depends('batch_id', 'batch_id.lead_job_id')
    def _compute_batch_flags(self):
        for job in self:
            job.is_batch_lead = bool(job.batch_id) and job.batch_id.lead_job_id == job
            job.counts_for_printer = not job.batch_id or job.is_batch_lead

    @api.depends('result', 'failure_reason', 'batch_id.job_ids.result', 'batch_id.job_ids.failure_reason')
    def _compute_printer_result(self):
        for job in self:
            source = job
            if job.batch_id:
                source = min(job.batch_id.job_ids, key=lambda j: RESULT_SEVERITY.index(j.result))
            job.printer_result = source.result
            job.printer_failure_reason = source.failure_reason

    @api.depends('duration_minutes', 'share')
    def _compute_allocated_minutes(self):
        for job in self:
            job.allocated_minutes = job.duration_minutes * job.share

    @api.depends('result', 'printer_result', 'is_batch_lead')
    def _compute_failure_count(self):
        for job in self:
            # The lead attempt carries the plate for the printer failure rate (SPEC 17, D-26).
            result = job.printer_result if job.is_batch_lead else job.result
            job.failure_count = 1 if result == 'failed' else 0

    @api.constrains('failure_reason', 'failure_note')
    def _check_failure_note(self):
        for job in self:
            if job.failure_reason == 'other' and not (job.failure_note or '').strip():
                raise ValidationError(_('Describe la falla cuando la causa es "Otro".'))

    # ------------------------------------------------------------------
    # Finish
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any(set(vals) & set(BATCH_FIELDS) for vals in vals_list):
            raise AccessError(_('Los datos de la impresión combinada solo los cambia su asistente.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and set(vals) & set(BATCH_FIELDS):
            raise AccessError(_('Los datos de la impresión combinada solo los cambia su asistente.'))
        return super().write(vals)

    def unlink(self):
        if self.mapped('consumption_ids').filtered('stock_move_id'):
            raise UserError(_('No se puede borrar un intento con consumo de filamento registrado.'))
        return super().unlink()

    def _action_open_finish_wizard(self, cancel_request=False):
        self.ensure_one()
        context = {'default_job_id': self.id}
        if cancel_request:
            context.update({'default_result': 'cancelled', 'default_cancel_request': True})
        return {
            'name': _('Terminar intento'),
            'type': 'ir.actions.act_window',
            'res_model': 'imago.print.job.finish.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': context,
        }

    def action_open_finish_wizard(self):
        self.ensure_one()
        self.request_id._check_operator()
        if self.result != 'running':
            raise UserError(_('El intento %s ya fue terminado.') % self.name)
        if self.batch_id:
            return self.batch_id._action_open_finish_wizard()
        return self._action_open_finish_wizard()

    def _finish(self, result, pieces_ok, lines, failure_reason=False, failure_note=False, labor_minutes=0,
                cancelling=False, from_batch=False):
        """Close a running attempt.

        :param lines: iterable of (lot, grams) captured by the operator.
        :param from_batch: only ``imago.print.batch._finish_combined`` closes the attempts of a
            combined print, all together (private parameter, not reachable through RPC).
        """
        self.ensure_one()
        if self.batch_id and not from_batch:
            raise UserError(_('El intento %(job)s es parte de la impresión combinada %(batch)s: termínala '
                              'completa desde [Terminar intento].', job=self.name, batch=self.batch_id.name))
        self._validate_finish(result, pieces_ok, lines, failure_reason, failure_note, labor_minutes)
        self._apply_consumption_lines(lines)
        self.consumption_ids._post_stock_move()
        if self.workorder_id:
            self.workorder_id.button_finish()
            self.env['mrp.workcenter']._invalidate_printer_status()
        keep_reason = result in RESULTS_REQUIRING_REASON + ('cancelled',) and failure_reason
        self.write({
            'result': result,
            'pieces_ok': pieces_ok,
            'failure_reason': failure_reason if keep_reason else False,
            'failure_note': failure_note if keep_reason else False,
            'labor_minutes': labor_minutes,
            'date_end': fields.Datetime.now(),
        })
        if labor_minutes > 0:
            self._create_labor_workorder(labor_minutes)
        self.request_id._after_job_finished(self, cancelling=cancelling)
        self.consumption_ids.mapped('lot_id')._spool_notify_low(request=self.request_id)
        return True

    def _validate_finish(self, result, pieces_ok, lines, failure_reason, failure_note, labor_minutes):
        if self.result != 'running':
            raise UserError(_('El intento %s ya fue terminado.') % self.name)
        if result not in dict(JOB_RESULTS) or result == 'running':
            raise UserError(_('Indica el resultado del intento.'))
        if pieces_ok < 0 or labor_minutes < 0:
            raise UserError(_('Las piezas y los minutos no pueden ser negativos.'))
        if result == 'ok' and pieces_ok <= 0:
            raise UserError(_('Un intento OK debe tener al menos una pieza OK; usa "Fallido" o "Cancelado".'))
        if labor_minutes > 0:
            self.request_id.company_id._print3d_get_labor_workcenter()
        if result in RESULTS_REQUIRING_REASON and not failure_reason:
            raise UserError(_('Indica la causa de la falla.'))
        if failure_reason == 'other' and not (failure_note or '').strip():
            raise UserError(_('Describe la falla cuando la causa es "Otro".'))
        if any(grams < 0 for _lot, grams in lines):
            raise UserError(_('Los gramos no pueden ser negativos.'))
        if result != 'cancelled' and not any(grams > 0 for _lot, grams in lines):
            raise UserError(_('Captura los gramos consumidos en al menos un carrete.'))

    def _apply_consumption_lines(self, lines):
        """Sync the captured (lot, grams) with the consumption records of the attempt."""
        grams_by_lot = {}
        for lot, grams in lines:
            grams_by_lot[lot] = grams_by_lot.get(lot, 0.0) + grams
        existing = {c.lot_id: c for c in self.consumption_ids}
        for lot, grams in grams_by_lot.items():
            if lot in existing:
                existing[lot].grams = grams
            else:
                self.env['imago.print.consumption'].create({
                    'job_id': self.id,
                    'workorder_id': self.workorder_id.id,
                    'lot_id': lot.id,
                    'grams': grams,
                })
        unused = self.consumption_ids.filtered(
            lambda c: not c.stock_move_id and (c.lot_id not in grams_by_lot or c.grams <= 0))
        # Operators cannot delete consumptions (ACL); these placeholders were never posted.
        unused.sudo().unlink()

    def _create_labor_workorder(self, minutes):
        """[LAB] work order with a done productivity line of ``minutes``."""
        self.ensure_one()
        request = self.request_id
        workcenter = request.company_id._print3d_get_labor_workcenter()
        production = request.production_id
        workorder = self.env['mrp.workorder'].create({
            'name': _('[LAB] Preparación/post-proceso – %s') % request.name,
            'production_id': production.id,
            'workcenter_id': workcenter.id,
            'product_uom_id': production.product_uom_id.id,
            'consumption': 'flexible',
            'duration_expected': minutes,
            'state': 'ready',
        })
        date_end = fields.Datetime.now()
        date_start = date_end - timedelta(minutes=minutes)
        loss = self.env['mrp.workcenter.productivity.loss'].search([('loss_type', '=', 'productive')], limit=1)
        if not loss:
            raise UserError(_('Define al menos una pérdida de productividad de tipo "Productivo" en Manufactura.'))
        self.env['mrp.workcenter.productivity'].create({
            'workorder_id': workorder.id,
            'workcenter_id': workcenter.id,
            'user_id': (self.operator_id or self.env.user).id,
            'loss_id': loss.id,
            'description': _('Mano de obra %s') % self.name,
            'date_start': date_start,
            'date_end': date_end,
            'company_id': production.company_id.id,
        })
        workorder.button_finish()
        workorder.write({'date_start': date_start})
        self.labor_workorder_id = workorder
        return workorder
