# -*- coding: utf-8 -*-
import math

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare, float_is_zero, float_round, html_escape

from .print_request import OPERATOR_GROUP

BATCH_STATES = [
    ('running', 'En curso'),
    ('done', 'Terminada'),
]
START_STATES = ('queued', 'post')
SHARE_TOLERANCE = 0.0001
# Written only by _start_combined / _finish_combined (as superuser, after their checks).
PROTECTED_FIELDS = ('name', 'workcenter_id', 'job_ids', 'lead_job_id', 'state', 'date_start', 'date_end',
                    'est_minutes', 'operator_id', 'company_id')


class PrintBatch(models.Model):
    """Several requests printed on the same plate (SPEC 17).

    Each request keeps its own attempt; the batch owns the shared facts (printer,
    spools, one [MCH] work order on the lead request's MO) and splits grams,
    machine minutes and labor by ``imago.print.job.share``.
    """

    _name = 'imago.print.batch'
    _description = 'Impresión combinada 3D'
    _inherit = ['mail.thread']
    _order = 'date_start desc, id desc'
    # Operators only read batches (ACL); they still post in the chatter.
    _mail_post_access = 'read'

    name = fields.Char(string='Folio', default=lambda self: _('Nuevo'), readonly=True, copy=False)
    workcenter_id = fields.Many2one(
        'mrp.workcenter', string='Impresora', required=True, readonly=True,
        domain="[('is_3d_printer', '=', True)]")
    job_ids = fields.One2many('imago.print.job', 'batch_id', string='Intentos', readonly=True)
    lead_job_id = fields.Many2one('imago.print.job', string='Intento líder', readonly=True)
    workorder_id = fields.Many2one(related='lead_job_id.workorder_id', string='WO [MCH]')
    request_ids = fields.Many2many(
        'imago.print.request', string='Solicitudes', compute='_compute_request_ids')
    state = fields.Selection(BATCH_STATES, string='Estado', default='running', required=True, readonly=True,
                             tracking=True)
    date_start = fields.Datetime(string='Inicio', readonly=True)
    date_end = fields.Datetime(string='Fin', readonly=True)
    est_minutes = fields.Integer(string='Minutos estimados (placa)', readonly=True)
    operator_id = fields.Many2one('res.users', string='Operador', readonly=True)
    company_id = fields.Many2one('res.company', string='Compañía', required=True, readonly=True,
                                 default=lambda self: self.env.company)

    @api.depends('job_ids.request_id')
    def _compute_request_ids(self):
        for batch in self:
            batch.request_ids = batch.job_ids.sorted('id').mapped('request_id')

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_('Las impresiones combinadas se crean desde [Iniciar impresión].'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and set(vals) & set(PROTECTED_FIELDS):
            raise AccessError(_('La impresión combinada solo cambia con sus asistentes.'))
        return super().write(vals)

    def unlink(self):
        if self.mapped('job_ids.consumption_ids').filtered('stock_move_id'):
            raise UserError(_('No se puede borrar una impresión combinada con consumo de filamento registrado.'))
        return super().unlink()

    # ------------------------------------------------------------------
    # Start
    # ------------------------------------------------------------------
    @api.model
    def _check_operator(self):
        if not self.env.su and not self.env.user.has_group(OPERATOR_GROUP):
            raise AccessError(_('Solo el operador de impresión 3D puede realizar esta acción.'))

    @api.model
    def _start_combined(self, requests, workcenter, lots, est_minutes, pieces=None, est_grams=None):
        """Start one plate for ``requests`` (the first one leads and owns the [MCH] WO).

        :param pieces: optional {request: pieces planned}; default the pending pieces.
        :param est_grams: optional {request: estimated grams}; default the request estimate.
        """
        self._check_operator()
        self._check_combinable(requests, est_minutes)
        pieces = pieces or {}
        est_grams = est_grams or {}
        planned = {r: pieces.get(r) or r.pieces_pending or r.qty_pieces for r in requests}
        grams = {r: est_grams.get(r, r.est_grams) for r in requests}
        for request in requests:
            request._check_start_conditions(workcenter, lots, planned[request])
        shares = self._default_shares(requests, grams)
        lead = requests[0]
        batch = self.sudo().create({
            'name': self.env['ir.sequence'].sudo().next_by_code('imago.print.batch') or _('Nuevo'),
            'workcenter_id': workcenter.id,
            'date_start': fields.Datetime.now(),
            'est_minutes': est_minutes,
            'operator_id': self.env.user.id,
            'company_id': lead.company_id.id,
        })
        productions = {request: request._ensure_production() for request in requests}
        workorder = lead._create_machine_workorder(
            productions[lead], workcenter,
            _('[MCH] Impresión 3D – %s (%s)') % (batch.name, ' + '.join(requests.mapped('name'))), est_minutes)
        jobs = self.env['imago.print.job']
        for request in requests:
            jobs |= request._create_job(
                workcenter, lots, planned[request], request._next_attempt_no(),
                workorder if request == lead else self.env['mrp.workorder'],
                est_grams=grams[request], est_minutes=est_minutes, batch=batch, share=shares[request])
        batch.lead_job_id = jobs[0]
        batch = batch.with_env(self.env)
        for request, job in zip(requests, jobs):
            request._after_job_started(job, workcenter, lots, batch=batch)
        batch.message_post(body=_('Impresión combinada iniciada en %(printer)s: %(requests)s.',
                                  printer=html_escape(workcenter.display_name),
                                  requests=html_escape(', '.join(requests.mapped('name')))))
        return batch

    @api.model
    def _check_combinable(self, requests, est_minutes):
        if len(requests) < 2:
            raise UserError(_('Elige al menos otra solicitud para imprimir junto con esta.'))
        requests._check_state(START_STATES, _('combinar'))
        if len(requests.mapped('company_id')) > 1:
            raise UserError(_('Solo se pueden combinar solicitudes de la misma compañía.'))
        busy = requests.filtered(lambda r: r.job_ids.filtered(lambda j: j.result == 'running'))
        if busy:
            raise UserError(_('Estas solicitudes ya tienen un intento en curso: %s') % ', '.join(busy.mapped('name')))
        if not est_minutes or est_minutes <= 0:
            raise UserError(_('Indica los minutos estimados de la placa completa.'))

    @api.model
    def _default_shares(self, requests, grams=None):
        """Proportional to the estimated grams; equal parts if any request has no estimate (D-23)."""
        grams = grams or {}
        weights = [grams.get(request, request.est_grams) for request in requests]
        if any(weight <= 0 for weight in weights):
            weights = [1.0] * len(requests)
        total = sum(weights)
        return {request: weight / total for request, weight in zip(requests, weights)}

    # ------------------------------------------------------------------
    # Finish
    # ------------------------------------------------------------------
    def _action_open_finish_wizard(self):
        self.ensure_one()
        self._check_operator()
        if self.state != 'running':
            raise UserError(_('La impresión combinada %s ya fue terminada.') % self.name)
        return {
            'name': _('Terminar impresión combinada %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'imago.print.batch.finish.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_batch_id': self.id},
        }

    def _finish_combined(self, lot_lines, request_lines, labor_minutes=0):
        """Close every attempt of the plate at once.

        :param lot_lines: iterable of (lot, grams) for the whole plate.
        :param request_lines: list of dicts with ``job``, ``result``, ``pieces_ok``,
            ``failure_reason``, ``failure_note`` and ``share`` (fraction).
        """
        self.ensure_one()
        self._check_operator()
        if self.state != 'running':
            raise UserError(_('La impresión combinada %s ya fue terminada.') % self.name)
        grams_by_lot = self._merge_lot_lines(lot_lines)
        self._validate_finish_lines(grams_by_lot, request_lines, labor_minutes)
        jobs = [line['job'] for line in request_lines]
        shares = [line['share'] for line in request_lines]
        allocation = self._split_grams(grams_by_lot, jobs, shares)
        self._check_allocation(request_lines, allocation, grams_by_lot)
        labor = self._split_minutes(labor_minutes, jobs, shares)
        for line in request_lines:
            job = line['job']
            job.sudo().write({'share': line['share']})
            job._finish(
                line['result'], line['pieces_ok'], allocation[job],
                failure_reason=line.get('failure_reason'), failure_note=line.get('failure_note'),
                labor_minutes=labor[job], from_batch=True)
        self.sudo().write({'state': 'done', 'date_end': fields.Datetime.now()})
        self.message_post(body=_('Impresión combinada terminada.'))
        return True

    @api.model
    def _merge_lot_lines(self, lot_lines):
        grams_by_lot = {}
        for lot, grams in lot_lines:
            if lot:
                grams_by_lot[lot] = grams_by_lot.get(lot, 0.0) + (grams or 0.0)
        return grams_by_lot

    def _validate_finish_lines(self, grams_by_lot, request_lines, labor_minutes):
        self.ensure_one()
        if {line['job'] for line in request_lines} != set(self.job_ids):
            raise UserError(_('Captura el resultado de todas las solicitudes de la impresión combinada.'))
        if labor_minutes < 0:
            raise UserError(_('Los minutos de mano de obra no pueden ser negativos.'))
        if any(grams < 0 for grams in grams_by_lot.values()):
            raise UserError(_('Los gramos no pueden ser negativos.'))
        total_share = sum(line['share'] for line in request_lines)
        if abs(total_share - 1.0) > SHARE_TOLERANCE:
            raise UserError(_('El reparto entre solicitudes debe sumar 100 %% (suma actual: %.2f %%).')
                            % (total_share * 100.0))
        for line in request_lines:
            if line['share'] < 0 or (line['share'] <= 0 and line['result'] != 'cancelled'):
                raise UserError(_('La solicitud %s necesita una parte mayor a cero del reparto.')
                                % line['job'].request_id.name)
        all_cancelled = all(line['result'] == 'cancelled' for line in request_lines)
        if not all_cancelled and not any(grams > 0 for grams in grams_by_lot.values()):
            raise UserError(_('Captura los gramos consumidos en al menos un carrete.'))
        for lot, grams in grams_by_lot.items():
            rounding = lot.product_id.uom_id.rounding
            available = lot._spool_available_g()
            if float_compare(grams, available, precision_rounding=rounding) > 0:
                raise UserError(_(
                    'El carrete %(lot)s solo tiene %(available).1f g disponibles en la ubicación 3D y '
                    'se intentan consumir %(grams).1f g. Usa [Pesar carrete] para corregir el inventario.',
                    lot=lot.name, available=max(available, 0.0), grams=grams))

    @api.model
    def _check_allocation(self, request_lines, allocation, grams_by_lot):
        """Before closing anything: every request that printed must receive some grams."""
        if not any(grams > 0 for grams in grams_by_lot.values()):
            return
        for line in request_lines:
            given = sum(grams for _lot, grams in allocation[line['job']])
            if line['result'] != 'cancelled' and given <= 0:
                raise UserError(_(
                    'La parte de %(request)s (%(pct).2f %%) no alcanza ni la unidad mínima de filamento; '
                    'ajusta el reparto o los gramos.', request=line['job'].request_id.name,
                    pct=line['share'] * 100.0))

    @api.model
    def _allocate(self, amount, shares, unit):
        """Largest-remainder split of ``amount`` in multiples of ``unit``: parts are never
        negative and add up to ``amount`` (rounded to ``unit``)."""
        total_units = int(round(amount / unit))
        raw = [total_units * share for share in shares]
        parts = [int(math.floor(value)) for value in raw]
        rest = total_units - sum(parts)
        order = sorted(range(len(shares)), key=lambda i: (-(raw[i] - parts[i]), -shares[i], i))
        for index in order[:rest]:
            parts[index] += 1
        return [part * unit for part in parts]

    @api.model
    def _split_grams(self, grams_by_lot, jobs, shares):
        """{job: [(lot, grams)]} with each spool split by the shares (D-24)."""
        allocation = {job: [] for job in jobs}
        for lot, grams in grams_by_lot.items():
            rounding = lot.product_id.uom_id.rounding
            if float_is_zero(grams, precision_rounding=rounding):
                continue
            for job, part in zip(jobs, self._allocate(grams, shares, rounding)):
                part = float_round(part, precision_rounding=rounding)
                if part > 0:
                    allocation[job].append((lot, part))
        return allocation

    @api.model
    def _split_minutes(self, minutes, jobs, shares):
        """Whole minutes per job (D-27)."""
        return dict(zip(jobs, [int(part) for part in self._allocate(minutes, shares, 1)]))
