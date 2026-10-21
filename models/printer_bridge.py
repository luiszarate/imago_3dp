# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .printer_telemetry import PAYLOAD_KEYS, TEXT_LIMITS, TelemetryError, parse_printer, parse_sent_at

_logger = logging.getLogger(__name__)

BRIDGE_GROUP = 'imago_3dp.group_print_bridge'
KEY_ADMIN_GROUP = 'base.group_erp_manager'
MIN_PUSH_INTERVAL = timedelta(seconds=3)
MIN_POLL_SECONDS = 5
IDLE_SNAPSHOT_SECONDS = 300


class PrinterBridge(models.Model):
    """Local bridge that reads the printers of the plant and pushes their state (SPEC 16.5.2).

    ``get_config`` and ``push_telemetry`` are called by the bridge's technical user
    through JSON-RPC; they check that user and then write as superuser.
    """

    _name = 'imago.printer.bridge'
    _description = 'Puente de impresoras 3D'
    _order = 'name'

    name = fields.Char(string='Nombre', required=True)
    user_id = fields.Many2one('res.users', string='Usuario técnico', required=True, ondelete='restrict',
                              help='Usuario con el grupo "Puente de impresoras (técnico)" y su API key.')
    active = fields.Boolean(default=True)
    poll_seconds = fields.Integer(string='Lectura cada (s)', default=10)
    snapshot_seconds = fields.Integer(string='Foto cada (s) al imprimir', default=30)
    config_version = fields.Integer(string='Versión de configuración', default=1, readonly=True)
    last_seen = fields.Datetime(string='Último envío', readonly=True)
    bridge_version = fields.Char(string='Versión del puente', readonly=True)
    workcenter_ids = fields.One2many('mrp.workcenter', 'bridge_id', string='Impresoras')
    is_online = fields.Boolean(string='En línea', compute='_compute_is_online')
    company_id = fields.Many2one('res.company', string='Compañía', default=lambda self: self.env.company)

    _sql_constraints = [
        ('user_unique', 'UNIQUE(user_id)', 'Cada puente necesita su propio usuario técnico.'),
        ('poll_min', 'CHECK(poll_seconds >= %d)' % MIN_POLL_SECONDS, 'El puente lee como mínimo cada 5 s.'),
        ('snapshot_min', 'CHECK(snapshot_seconds >= 10)', 'Las fotos se toman como mínimo cada 10 s.'),
    ]

    api_key_count = fields.Integer(string='API keys activas', compute='_compute_api_key_count')

    @api.constrains('user_id')
    def _check_technical_user(self):
        """A portal user with only the bridge group: it can call the API but cannot read
        requests, stock or anything else (SPEC 16.8)."""
        for bridge in self:
            user = bridge.user_id
            if not user.has_group(BRIDGE_GROUP) or user.has_group('base.group_user'):
                raise ValidationError(_('El usuario técnico de %s debe ser un usuario portal con el grupo '
                                        '"Puente de impresoras (técnico)" y sin acceso interno.') % bridge.name)

    def _compute_api_key_count(self):
        Keys = self.env['res.users.apikeys'].sudo()
        for bridge in self:
            bridge.api_key_count = Keys.search_count([('user_id', '=', bridge.user_id.id)])

    def action_generate_api_key(self):
        """Create an RPC key for the technical user (nobody logs in as it) and show it once."""
        self.ensure_one()
        if not self.env.user.has_group(KEY_ADMIN_GROUP):
            raise AccessError(_('Solo un administrador de accesos puede generar la API key del puente.'))
        bridge = self.sudo()
        bridge._check_technical_user()
        key = self.env['res.users.apikeys'].with_user(bridge.user_id)._generate('rpc', _('Puente %s') % bridge.name)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.users.apikeys.show',
            'name': _('API key del puente (cópiala ahora, no se vuelve a mostrar)'),
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_key': key},
        }

    def action_revoke_api_keys(self):
        self.ensure_one()
        if not self.env.user.has_group(KEY_ADMIN_GROUP):
            raise AccessError(_('Solo un administrador de accesos puede revocar las API keys del puente.'))
        keys = self.env['res.users.apikeys'].sudo().search([('user_id', '=', self.sudo().user_id.id)])
        if not keys:
            raise UserError(_('El usuario técnico no tiene API keys.'))
        keys._remove()
        return True

    @api.depends('last_seen', 'poll_seconds')
    def _compute_is_online(self):
        now = fields.Datetime.now()
        for bridge in self:
            window = timedelta(seconds=3 * max(bridge.poll_seconds, MIN_POLL_SECONDS))
            bridge.is_online = bool(bridge.last_seen and now - bridge.last_seen <= window)

    def _bump_config_version(self):
        for bridge in self.sudo():
            bridge.config_version += 1

    # ------------------------------------------------------------------
    # JSON-RPC API for the bridge
    # ------------------------------------------------------------------
    @api.model
    def _current_bridge(self):
        """The active bridge owned by the calling technical user, or AccessError."""
        if not self.env.user.has_group(BRIDGE_GROUP):
            raise AccessError(_('Solo el usuario técnico de un puente puede usar esta API.'))
        if self.env.user.has_group('base.group_user'):
            # A key keeps working if the user is later promoted: refuse internal users here too.
            raise AccessError(_('El usuario técnico del puente no puede ser un usuario interno.'))
        bridge = self.sudo().search([('user_id', '=', self.env.uid), ('active', '=', True)], limit=1)
        if not bridge:
            raise AccessError(_('Este usuario no está asignado a un puente activo.'))
        return bridge

    @api.model
    def get_config(self):
        bridge = self._current_bridge()
        printers = bridge.workcenter_ids.filtered(lambda w: w.active and w.printer_driver != 'none')
        return {
            'config_version': bridge.config_version,
            'poll_seconds': bridge.poll_seconds,
            'snapshot_seconds': bridge.snapshot_seconds,
            'idle_snapshot_seconds': IDLE_SNAPSHOT_SECONDS,
            'printers': [{
                'workcenter_id': printer.id,
                'code': printer.code or printer.name,
                'driver': printer.printer_driver,
                'host': (printer.printer_host or '').strip(),
                'port': printer.printer_port,
                'camera_url': (printer.camera_url or '').strip() or False,
            } for printer in printers],
        }

    @api.model
    def push_telemetry(self, payload):
        bridge = self._current_bridge()
        now = fields.Datetime.now()
        # Row lock: concurrent pushes cannot both pass the rate limit.
        self.env.cr.execute('SELECT id FROM imago_printer_bridge WHERE id = %s FOR UPDATE', (bridge.id,))
        bridge.invalidate_cache(['last_seen'])
        if bridge.last_seen and now - bridge.last_seen < MIN_PUSH_INTERVAL:
            return {'ok': False, 'error': 'rate_limited', 'config_version': bridge.config_version}
        try:
            reported_at = bridge._check_payload(payload, now)
        except TelemetryError as error:
            _logger.warning('Puente %s: lote rechazado (%s)', bridge.name, error)
            return {'ok': False, 'error': str(error), 'config_version': bridge.config_version}
        errors = bridge._apply_printers(payload['printers'], reported_at, now)
        version = payload.get('bridge_version')
        bridge.write({
            'last_seen': now,
            'bridge_version': version[:TEXT_LIMITS['bridge_version']] if isinstance(version, str) else False,
        })
        return {'ok': True, 'config_version': bridge.config_version, 'errors': errors}

    def _check_payload(self, payload, now):
        self.ensure_one()
        if not isinstance(payload, dict) or set(payload) - PAYLOAD_KEYS:
            raise TelemetryError('format')
        printers = payload.get('printers')
        if not isinstance(printers, list):
            raise TelemetryError('printers')
        # Generous cap (invalid entries are reported back), but a push cannot be inflated at will.
        if len(printers) > 2 * max(len(self.workcenter_ids), 1):
            raise TelemetryError('too_many_printers')
        return parse_sent_at(payload.get('sent_at'), now)

    def _apply_printers(self, items, reported_at, now):
        """Store each valid printer entry; an invalid one never blocks the others (A-22)."""
        self.ensure_one()
        allowed = set(self.workcenter_ids.ids)
        Status = self.env['imago.printer.status'].sudo()
        errors = []
        seen = set()
        for item in items:
            workcenter_id = item.get('workcenter_id') if isinstance(item, dict) else None
            valid_id = workcenter_id if type(workcenter_id) is int else False
            try:
                if valid_id not in allowed:
                    raise TelemetryError('workcenter_id')
                if valid_id in seen:
                    raise TelemetryError('duplicate')
                seen.add(valid_id)
                values, snapshot = parse_printer(item)
            except TelemetryError as error:
                errors.append({'workcenter_id': valid_id, 'error': str(error)})
                continue
            except (ValueError, OverflowError, TypeError):
                # Hostile values must never abort the batch (A-22).
                errors.append({'workcenter_id': valid_id, 'error': 'format'})
                continue
            if item.get('snapshot_jpeg_b64') and snapshot is None:
                errors.append({'workcenter_id': workcenter_id, 'error': 'snapshot_rejected'})
            Status._record(self, workcenter_id, values, snapshot, reported_at, now)
        return errors
