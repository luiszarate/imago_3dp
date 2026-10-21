# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError
from odoo.tools import html_escape

from .printer_status import STATE_SELECTION

EVENT_TYPES = [
    ('started', 'Inició'),
    ('paused', 'En pausa'),
    ('resumed', 'Reanudó'),
    ('finished', 'Terminó'),
    ('error', 'Error'),
    ('offline', 'Sin comunicación'),
    ('online', 'Comunicación restablecida'),
    ('unregistered', 'Impresión no registrada'),
    ('finished_open', 'Terminó con intento abierto'),
]
ALERT_ACTIVITY = 'imago_3dp.mail_activity_printer_alert'
DEFAULT_OFFLINE_ALERT_MIN = 10
DEFAULT_FINISHED_ALERT_MIN = 5
# A flapping condition (or a hostile bridge) must not flood the operator's inbox.
ALERT_COOLDOWN = timedelta(minutes=10)
EVENT_RETENTION_DAYS = 365


class PrinterEvent(models.Model):
    """State changes and alerts of a printer (SPEC 16.5.4 / 16.7). Immutable except as superuser."""

    _name = 'imago.printer.event'
    _description = 'Evento de impresora 3D'
    _order = 'date desc, id desc'

    workcenter_id = fields.Many2one('mrp.workcenter', string='Impresora', required=True, ondelete='cascade',
                                    index=True)
    status_id = fields.Many2one('imago.printer.status', string='Estado en vivo', ondelete='cascade')
    date = fields.Datetime(string='Fecha', required=True, default=fields.Datetime.now)
    event_type = fields.Selection(EVENT_TYPES, string='Evento', required=True)
    state_from = fields.Selection(STATE_SELECTION, string='Desde')
    state_to = fields.Selection(STATE_SELECTION, string='Hacia')
    workorder_id = fields.Many2one('mrp.workorder', string='WO en progreso', ondelete='set null')
    job_id = fields.Many2one('imago.print.job', string='Intento en curso', ondelete='set null')
    request_id = fields.Many2one(related='job_id.request_id', string='Solicitud', store=True)
    details = fields.Char(string='Detalle')
    is_alert = fields.Boolean(string='Alerta')
    alert_open = fields.Boolean(string='Alerta abierta', index=True)
    date_closed = fields.Datetime(string='Alerta cerrada')
    activity_id = fields.Many2one('mail.activity', string='Actividad', ondelete='set null')
    company_id = fields.Many2one(related='workcenter_id.company_id', store=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_('Los eventos de impresora los registra solo el sistema.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            raise AccessError(_('Los eventos de impresora no se modifican.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.su:
            raise AccessError(_('Los eventos de impresora no se borran.'))
        return super().unlink()

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------
    @api.model
    def _transition_type(self, previous, state):
        if previous == 'offline' and state != 'offline':
            return 'online'
        if state == 'printing':
            return 'resumed' if previous == 'paused' else 'started'
        return {'paused': 'paused', 'finished': 'finished', 'error': 'error', 'offline': 'offline'}.get(state)

    @api.model
    def _on_transition(self, status, previous, state, now):
        event_type = self._transition_type(previous, state)
        if not event_type:
            return self.browse()
        workorder, job = self._running(status.workcenter_id)
        return self.create({
            'workcenter_id': status.workcenter_id.id, 'status_id': status.id, 'date': now,
            'event_type': event_type, 'state_from': previous, 'state_to': state,
            'workorder_id': workorder.id, 'job_id': job.id,
            'details': status.error_text if state == 'error' else status.file_name,
        })

    @api.model
    def _running(self, printer):
        workorder = printer._printer_running_workorder()
        job = self.env['imago.print.job'].sudo().search(
            [('workorder_id', '=', workorder.id), ('result', '=', 'running')], limit=1) if workorder \
            else self.env['imago.print.job']
        return workorder, job

    # ------------------------------------------------------------------
    # Alerts (SPEC 16.7): opened once per condition, closed when it clears
    # ------------------------------------------------------------------
    @api.model
    def _sync_alerts(self, status, now):
        printer = status.workcenter_id
        if printer.out_of_service:
            self._close_alerts(printer, ('unregistered', 'error', 'offline', 'finished_open'), now)
            return
        workorder, job = self._running(printer)
        for alert_type, active in self._alert_conditions(status, workorder, job, now).items():
            open_alert = self.search([('workcenter_id', '=', printer.id), ('event_type', '=', alert_type),
                                      ('alert_open', '=', True)], limit=1)
            if active and not open_alert and not self._recently_closed(printer, alert_type, now):
                self._open_alert(alert_type, status, workorder, job, now)
            elif not active and open_alert:
                open_alert._close(now)

    @api.model
    def _recently_closed(self, printer, alert_type, now):
        return bool(self.search_count([
            ('workcenter_id', '=', printer.id), ('event_type', '=', alert_type), ('alert_open', '=', False),
            ('is_alert', '=', True), ('date_closed', '>', now - ALERT_COOLDOWN)]))

    @api.model
    def _purge_old(self, now):
        """Keep a year of history (state flapping would otherwise grow the table forever)."""
        self.search([('alert_open', '=', False), ('date', '<', now - timedelta(days=EVENT_RETENTION_DAYS))]).unlink()

    @api.model
    def _alert_conditions(self, status, workorder, job, now):
        company = status.workcenter_id.company_id
        offline_after = timedelta(minutes=company.print3d_offline_alert_min or DEFAULT_OFFLINE_ALERT_MIN)
        finished_after = timedelta(minutes=company.print3d_finished_alert_min or DEFAULT_FINISHED_ALERT_MIN)
        fresh = not status.is_stale
        silent = not status.received_at or now - status.received_at > offline_after
        # "Finished" needs a print the bridge saw end after the attempt started (a CR-M4
        # pre-heating also reads as idle).
        printed_and_ended = bool(job and status.print_finished_at and job.date_start
                                 and status.print_finished_at >= job.date_start)
        return {
            'unregistered': fresh and status.state == 'printing' and not workorder,
            'error': fresh and status.state == 'error',
            'offline': bool(workorder) and (silent or status.state == 'offline'),
            'finished_open': fresh and printed_and_ended and status.state in ('finished', 'idle')
            and status.state_since and now - status.state_since >= finished_after,
        }

    @api.model
    def _open_alert(self, alert_type, status, workorder, job, now):
        event = self.create({
            'workcenter_id': status.workcenter_id.id, 'status_id': status.id, 'date': now,
            'event_type': alert_type, 'state_to': status.state, 'workorder_id': workorder.id,
            'job_id': job.id, 'is_alert': True, 'alert_open': True,
            'details': status.error_text or status.file_name,
        })
        event._schedule_activity()
        return event

    def _alert_text(self):
        self.ensure_one()
        printer = self.workcenter_id.display_name
        return {
            'unregistered': _('%s está imprimiendo sin intento iniciado en Odoo.') % printer,
            'error': _('%(printer)s reporta un error: %(error)s') % {'printer': printer,
                                                                   'error': self.details or '-'},
            'offline': _('Sin comunicación con %s y hay una impresión en curso en Odoo.') % printer,
            'finished_open': _('Terminó la impresión en %(printer)s: cierra el intento %(job)s.') % {
                'printer': printer, 'job': self.job_id.name or ''},
        }[self.event_type]

    def _schedule_activity(self):
        self.ensure_one()
        activity_type = self.env.ref(ALERT_ACTIVITY, raise_if_not_found=False)
        if self.event_type == 'finished_open' and self.job_id:
            record = self.job_id.request_id
            user = self.job_id.operator_id or record.operator_id
        else:
            record = self.status_id
            user = self.workcenter_id.company_id.print3d_default_operator_id
        if not (activity_type and record and user):
            return
        # Authored by OdooBot, not by the bridge's technical (portal) user.
        activity = record.with_user(SUPERUSER_ID).activity_schedule(
            ALERT_ACTIVITY, summary=self._alert_text(), note=html_escape(self._alert_text()), user_id=user.id)
        self.activity_id = activity

    def _close(self, now):
        for event in self:
            if event.activity_id.exists():
                event.activity_id.with_user(SUPERUSER_ID).action_feedback(
                    feedback=_('Resuelto: la condición desapareció.'))
            event.write({'alert_open': False, 'date_closed': now})

    @api.model
    def _close_alerts(self, printer, alert_types, now):
        self.search([('workcenter_id', '=', printer.id), ('event_type', 'in', alert_types),
                     ('alert_open', '=', True)])._close(now)
