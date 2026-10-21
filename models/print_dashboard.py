# -*- coding: utf-8 -*-
from collections import defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .print_job import FAILURE_REASONS
from .print_request import OPERATOR_GROUP

QUEUE_STATES = ('submitted', 'queued', 'post')
QUEUE_LIMIT = 30
FINISHED_RESULTS = ('ok', 'partial', 'failed')
RECENT_JOBS = 3
KPI_DAYS = 7
PROGRESS_EST_CAP = 99.0
ACTIONS_LIMIT = 12
LATE_ACTIONS_LIMIT = 5
SEVERITY_ORDER = {'critical': 0, 'warning': 1, 'info': 2}
# Within a severity: what unblocks a machine or a late piece first.
KIND_ORDER = ('late', 'filament', 'overdue', 'spool', 'review', 'idle', 'deliver')
SHORT_DATE = '%d/%m'


class PrintDashboard(models.AbstractModel):
    """Data for the operator dashboard client action (SPEC 16.10).

    Charts live in ``print_dashboard_charts.py``.
    """

    _name = 'imago.print.dashboard'
    _description = 'Dashboard de impresión 3D'

    @api.model
    def get_dashboard_data(self, include_charts=True):
        if not self.env.user.has_group(OPERATOR_GROUP):
            raise AccessError(_('Solo el operador de impresión 3D puede ver el dashboard.'))
        now = fields.Datetime.now()
        printers = self.env['mrp.workcenter'].search([('is_3d_printer', '=', True)], order='code, name')
        cards = [self._printer_card(printer, now) for printer in printers]
        queue = self._queue_rows()
        data = {
            'generated_at': fields.Datetime.to_string(now),
            'kpis': self._kpis(cards, now),
            'actions': self._actions(cards, queue, now),
            'printers': cards,
            'queue': queue,
            'spools': self._spools(),
        }
        if include_charts:
            data['charts'] = self._charts(printers, now)
        return data

    # ------------------------------------------------------------------
    # Stations
    # ------------------------------------------------------------------
    def _printer_card(self, printer, now):
        status_labels = dict(printer._fields['printer_status'].selection)
        Job = self.env['imago.print.job']
        job = Job.search(
            [('workorder_id', '=', printer.current_workorder_id.id), ('result', '=', 'running')], limit=1,
        ) if printer.current_workorder_id else Job
        spool = printer.mounted_lot_id
        return {
            'id': printer.id,
            'name': printer.name,
            'code': printer.code or '',
            'model': printer.printer_model or '',
            'status': printer.printer_status,
            'status_label': status_labels.get(printer.printer_status, ''),
            'workorder': self._record_ref(printer.current_workorder_id),
            'request': self._request_ref(printer.current_request_id),
            'job': self._job_info(job, now) if job else False,
            'eta': fields.Datetime.to_string(printer.current_eta) if printer.current_eta else False,
            'spool': self._spool_info(spool) if spool else False,
            'filament_warning': bool(job and spool and job.est_grams > spool.spool_remaining_g),
            'recent_jobs': self._recent_jobs(printer),
        }

    @api.model
    def _record_ref(self, record):
        return {'id': record.id, 'name': record.display_name} if record else False

    @api.model
    def _request_ref(self, request):
        if not request:
            return False
        return {
            'id': request.id,
            'name': request.name,
            'title': request.title,
            'requester': request.requester_id.name,
        }

    @api.model
    def _job_info(self, job, now):
        elapsed = (now - job.date_start).total_seconds() / 60.0 if job.date_start else 0.0
        progress = min(elapsed / job.est_minutes * 100.0, PROGRESS_EST_CAP) if job.est_minutes else 0.0
        return {
            'id': job.id,
            'name': job.name,
            'date_start': fields.Datetime.to_string(job.date_start) if job.date_start else False,
            'elapsed_minutes': round(elapsed),
            'est_minutes': job.est_minutes,
            'est_grams': job.est_grams,
            'progress_est': round(progress, 1),
            'overdue': bool(job.est_minutes and elapsed > job.est_minutes),
        }

    @api.model
    def _spool_info(self, spool):
        return {
            'id': spool.id,
            'name': spool.name,
            'product': spool.product_id.display_name,
            'remaining_g': spool.spool_remaining_g,
            'remaining_pct': spool.spool_remaining_pct,
            'state': spool.spool_state,
        }

    def _recent_jobs(self, printer):
        jobs = self.env['imago.print.job'].search(
            [('workcenter_id', '=', printer.id), ('result', '!=', 'running')],
            order='date_end desc, id desc', limit=RECENT_JOBS)
        results = dict(jobs._fields['result'].selection)
        reasons = dict(FAILURE_REASONS)
        return [{
            'id': job.id,
            'name': job.name,
            'result': job.result,
            'result_label': results[job.result],
            'reason_label': reasons.get(job.failure_reason, ''),
            'date_end': fields.Datetime.to_string(job.date_end) if job.date_end else False,
        } for job in jobs]

    # ------------------------------------------------------------------
    # Queue, spools, KPIs
    # ------------------------------------------------------------------
    def _queue_rows(self):
        requests = self.env['imago.print.request'].search(
            [('state', 'in', QUEUE_STATES)], order='priority desc, date_required asc, id asc', limit=QUEUE_LIMIT)
        state_labels = dict(requests._fields['state'].selection)
        return [{
            'id': request.id,
            'name': request.name,
            'title': request.title,
            'state': request.state,
            'state_label': state_labels[request.state],
            'priority': int(request.priority or 0),
            'date_required': fields.Date.to_string(request.date_required) if request.date_required else False,
            'is_late': request.is_late,
            'requester': request.requester_id.name,
            'filament': request.filament_product_id.display_name,
            'qty_pieces': request.qty_pieces,
            'printer_id': request.planned_workcenter_id.id,
            'printer': request.planned_workcenter_id.display_name or '',
        } for request in requests]

    def _spools(self):
        """Stock summary per filament plus the spools that need a look:
        nearly empty ones and the ones mounted on a printer."""
        lots = self.env['stock.production.lot'].search(
            [('is_spool', '=', True), ('spool_state', 'in', ('new', 'open', 'low'))])
        mounted = self.env['mrp.workcenter'].search(
            [('is_3d_printer', '=', True), ('mounted_lot_id', '!=', False)])
        printer_by_lot = {printer.mounted_lot_id.id: printer.name for printer in mounted}
        summary = defaultdict(lambda: {'spools': 0, 'grams': 0.0, 'low': 0})
        for lot in lots:
            row = summary[lot.product_id]
            row['spools'] += 1
            row['grams'] += lot.spool_remaining_g
            row['low'] += 1 if lot.spool_state == 'low' else 0
        critical = (lots.filtered(lambda lot: lot.spool_state == 'low') | mounted.mapped('mounted_lot_id'))
        return {
            'summary': sorted([{
                'product_id': product.id,
                'product': product.display_name,
                'material': product.filament_material_id.name or '',
                'spools': row['spools'],
                'grams': round(row['grams']),
                'low': row['low'],
            } for product, row in summary.items()], key=lambda row: (row['material'], row['product'])),
            'critical': sorted([dict(self._spool_info(lot), printer=printer_by_lot.get(lot.id, ''))
                                for lot in critical], key=lambda row: row['remaining_g']),
        }

    def _kpis(self, cards, now):
        Request = self.env['imago.print.request']
        jobs = self.env['imago.print.job'].search([
            ('result', 'in', FINISHED_RESULTS),
            ('date_end', '>=', now - timedelta(days=KPI_DAYS)),
        ])
        failed = len(jobs.filtered(lambda job: job.result == 'failed'))
        return {
            'printers': len(cards),
            'printing': len([card for card in cards if card['status'] == 'printing']),
            'queued': Request.search_count([('state', '=', 'queued')]),
            'submitted': Request.search_count([('state', '=', 'submitted')]),
            'post': Request.search_count([('state', '=', 'post')]),
            'late': Request.search_count([('is_late', '=', True)]),
            'low_spools': self.env['stock.production.lot'].search_count(
                [('is_spool', '=', True), ('spool_state', '=', 'low')]),
            'jobs_7d': len(jobs),
            'failure_rate_7d': round(failed * 100.0 / len(jobs), 1) if jobs else False,
        }

    # ------------------------------------------------------------------
    # Action strip
    # ------------------------------------------------------------------
    def _actions(self, cards, queue, now):
        actions = self._queue_actions(queue) + self._station_actions(cards, queue)
        actions.sort(key=lambda action: (SEVERITY_ORDER[action['severity']], KIND_ORDER.index(action['kind'])))
        return actions[:ACTIONS_LIMIT]

    @api.model
    def _action(self, kind, severity, title, detail, button=False, open_ref=False):
        return {
            'key': '%s-%s' % (kind, (button or open_ref or {}).get('id', '')),
            'kind': kind, 'severity': severity, 'title': title, 'detail': detail,
            'button': button, 'open': open_ref,
        }

    @api.model
    def _button(self, label, model, method, res_id):
        return {'label': label, 'model': model, 'method': method, 'id': res_id}

    @api.model
    def _request_open(self, row):
        return {'model': 'imago.print.request', 'id': row['id']}

    def _queue_actions(self, queue):
        actions = []
        for row in [row for row in queue if row['is_late']][:LATE_ACTIONS_LIMIT]:
            button = self._button(_('Iniciar'), 'imago.print.request', 'action_open_start_wizard', row['id']) \
                if row['state'] == 'queued' else False
            actions.append(self._action(
                'late', 'critical', _('Atrasada: %s') % row['name'],
                _('%(title)s · requerida %(date)s') % {
                    'title': row['title'],
                    'date': fields.Date.from_string(row['date_required']).strftime(SHORT_DATE)},
                button, self._request_open(row)))
        for row in queue:
            if row['state'] == 'submitted':
                actions.append(self._action('review', 'warning', _('Por revisar: %s') % row['name'],
                                            '%s · %s' % (row['title'], row['requester']),
                                            open_ref=self._request_open(row)))
            elif row['state'] == 'post':
                actions.append(self._action('deliver', 'info', _('Post-proceso: %s') % row['name'],
                                            _('%s · entregar al terminar') % row['title'],
                                            open_ref=self._request_open(row)))
        return actions

    def _station_actions(self, cards, queue):
        actions = []
        for card in cards:
            job, spool = card['job'], card['spool']
            mount = self._button(_('Montar carrete'), 'mrp.workcenter', 'action_open_mount_wizard', card['id'])
            if job and job['overdue'] and card['request']:
                actions.append(self._action(
                    'overdue', 'warning', _('%s: ¿ya terminó?') % card['name'],
                    _('%(job)s superó su estimado de %(min)s min') % {'job': job['name'], 'min': job['est_minutes']},
                    self._button(_('Terminar intento'), 'imago.print.request', 'action_open_finish_wizard',
                                 card['request']['id'])))
            if card['filament_warning']:
                actions.append(self._action(
                    'filament', 'critical', _('%s: filamento insuficiente') % card['name'],
                    _('El intento espera %(need).0f g y el carrete tiene %(left).0f g') % {
                        'need': job['est_grams'], 'left': spool['remaining_g']}, mount))
            elif spool and spool['state'] in ('low', 'empty'):
                actions.append(self._action(
                    'spool', 'warning', _('%s: carrete casi vacío') % card['name'],
                    _('%(spool)s · quedan %(left).0f g') % {'spool': spool['name'], 'left': spool['remaining_g']},
                    mount))
            waiting = [row for row in queue if row['state'] == 'queued' and row['printer_id'] == card['id']]
            if card['status'] == 'free' and waiting:
                actions.append(self._action(
                    'idle', 'info', _('%s libre') % card['name'],
                    _('Siguiente en cola: %(name)s · %(title)s') % waiting[0],
                    self._button(_('Iniciar'), 'imago.print.request', 'action_open_start_wizard', waiting[0]['id'])))
        return actions
