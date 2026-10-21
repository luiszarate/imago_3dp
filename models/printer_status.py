# -*- coding: utf-8 -*-
import base64
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .printer_telemetry import PRINTER_STATES

STATE_SELECTION = [
    ('offline', 'Apagada / sin red'),
    ('idle', 'En reposo'),
    ('printing', 'Imprimiendo'),
    ('paused', 'En pausa'),
    ('finished', 'Terminada'),
    ('error', 'Error'),
    ('unknown', 'Desconocido'),
]
assert {key for key, _label in STATE_SELECTION} == set(PRINTER_STATES)
DEFAULT_STALE_SECONDS = 60


class PrinterStatus(models.Model):
    """Last state reported by the bridge for one printer (SPEC 16.5.3).

    Written only by the bridge API and the alert cron, as superuser.
    """

    _name = 'imago.printer.status'
    _description = 'Estado en vivo de impresora 3D'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'workcenter_id'
    _mail_post_access = 'read'

    workcenter_id = fields.Many2one('mrp.workcenter', string='Impresora', required=True, ondelete='cascade',
                                    index=True)
    bridge_id = fields.Many2one('imago.printer.bridge', string='Puente', ondelete='set null')
    reachable = fields.Boolean(string='Alcanzable')
    state = fields.Selection(STATE_SELECTION, string='Estado', default='unknown', required=True)
    state_since = fields.Datetime(string='En este estado desde')
    progress = fields.Float(string='Avance (%)')
    progress_known = fields.Boolean(string='Avance reportado')
    nozzle_temp = fields.Float(string='Boquilla (°C)')
    nozzle_target = fields.Float(string='Objetivo boquilla (°C)')
    bed_temp = fields.Float(string='Cama (°C)')
    bed_target = fields.Float(string='Objetivo cama (°C)')
    layer = fields.Integer(string='Capa')
    layer_total = fields.Integer(string='Capas totales')
    time_left_min = fields.Integer(string='Minutos restantes')
    job_time_min = fields.Integer(string='Minutos de impresión (impresora)')
    file_name = fields.Char(string='Archivo')
    error_text = fields.Char(string='Error')
    reported_at = fields.Datetime(string='Reportado por el puente')
    received_at = fields.Datetime(string='Recibido en Odoo')
    print_started_at = fields.Datetime(string='Inicio detectado',
                                       help='Primera lectura en "Imprimiendo" de la impresión actual o última.')
    print_finished_at = fields.Datetime(string='Fin detectado')
    snapshot = fields.Binary(string='Foto', attachment=True)
    snapshot_at = fields.Datetime(string='Foto tomada')
    is_stale = fields.Boolean(string='Sin datos recientes', compute='_compute_is_stale')
    company_id = fields.Many2one(related='workcenter_id.company_id', store=True)

    _sql_constraints = [
        ('workcenter_unique', 'UNIQUE(workcenter_id)', 'Cada impresora tiene un solo estado en vivo.'),
    ]

    def _compute_is_stale(self):
        now = fields.Datetime.now()
        for status in self:
            limit = timedelta(seconds=status.company_id.print3d_telemetry_stale_s or DEFAULT_STALE_SECONDS)
            status.is_stale = not status.received_at or now - status.received_at > limit

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_('El estado en vivo lo escribe solo el puente.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and set(vals) & set(self._fields) - set(self.env['mail.thread']._fields) \
                - set(self.env['mail.activity.mixin']._fields):
            raise AccessError(_('El estado en vivo lo escribe solo el puente.'))
        return super().write(vals)

    # ------------------------------------------------------------------
    # Recording (called by imago.printer.bridge.push_telemetry as superuser)
    # ------------------------------------------------------------------
    @api.model
    def _record(self, bridge, workcenter_id, values, snapshot, reported_at, now):
        status = self.search([('workcenter_id', '=', workcenter_id)], limit=1)
        if not status:
            # First reading: start from "unknown" so a print already running is detected as started.
            status = self.create({'workcenter_id': workcenter_id, 'state': 'unknown', 'state_since': now})
        previous_state, was_reachable = status.state, status.reachable
        state = values['state'] if values['reachable'] else 'offline'
        vals = dict(values, state=state, bridge_id=bridge.id, reported_at=reported_at, received_at=now)
        if state != previous_state:
            vals['state_since'] = now
        vals.update(status._print_window(previous_state, state, now))
        if snapshot is not None:
            vals.update({'snapshot': base64.b64encode(snapshot), 'snapshot_at': now})
        status.write(vals)
        if state != previous_state or was_reachable != values['reachable']:
            self.env['imago.printer.event']._on_transition(status, previous_state, state, now)
        status._sync_alerts(now)
        return status

    def _print_window(self, previous_state, state, now):
        """Detected start/end of the physical print, used to prefill the real print time."""
        self.ensure_one()
        if state == 'printing' and previous_state not in ('printing', 'paused'):
            return {'print_started_at': now, 'print_finished_at': False}
        if previous_state in ('printing', 'paused') and state in ('finished', 'idle') and self.print_started_at:
            return {'print_finished_at': now}
        return {}

    def _detected_print_minutes(self):
        """Real print minutes from the printer, or 0 when it did not report them."""
        self.ensure_one()
        if self.job_time_min:
            return self.job_time_min
        if self.print_started_at and self.print_finished_at and self.print_finished_at > self.print_started_at:
            return round((self.print_finished_at - self.print_started_at).total_seconds() / 60.0)
        return 0

    @api.model
    def _for_printer(self, printer):
        """Fresh read (the computed ``live_status_id`` may be cached in the transaction)."""
        return self.sudo().search([('workcenter_id', '=', printer.id)], limit=1)

    def _sync_alerts(self, now):
        self.env['imago.printer.event']._sync_alerts(self, now)

    @api.model
    def _cron_check_alerts(self):
        now = fields.Datetime.now()
        for status in self.sudo().search([]):
            status._sync_alerts(now)
        self.env['imago.printer.event'].sudo()._purge_old(now)
        return True
