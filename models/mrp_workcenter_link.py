# -*- coding: utf-8 -*-
import ipaddress
from urllib.parse import urlsplit

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

PRINTER_DRIVERS = [
    ('none', 'Sin conexión'),
    ('creality_box', 'Creality WiFi Box (HTTP 81)'),
    ('flashforge_tcp', 'Flashforge (TCP 8899)'),
]
DEFAULT_PORTS = {'creality_box': 81, 'flashforge_tcp': 8899}
DEFAULT_CAMERA = {'flashforge_tcp': 'http://%s:8080/?action=stream'}
LINK_FIELDS = ('printer_driver', 'printer_host', 'printer_port', 'camera_url', 'bridge_id', 'active', 'code')
LIVE_STATES = [
    ('no_link', 'Sin conexión'),
    ('stale', 'Sin datos'),
    ('offline', 'Apagada / sin red'),
    ('idle', 'En reposo'),
    ('printing', 'Imprimiendo'),
    ('paused', 'En pausa'),
    ('finished', 'Terminada'),
    ('error', 'Error'),
    ('unknown', 'Desconocido'),
]


def is_private_ipv4(host):
    """Only literal private IPv4 addresses: no DNS names, loopback or link-local (SPEC 16, D-19)."""
    try:
        address = ipaddress.ip_address((host or '').strip())
    except ValueError:
        return False
    return (address.version == 4 and address.is_private and not address.is_loopback
            and not address.is_link_local and not address.is_multicast and not address.is_unspecified)


class MrpWorkcenter(models.Model):
    """Network link of a 3D printer, read by the local bridge (SPEC 16.5.1)."""

    _inherit = 'mrp.workcenter'

    printer_driver = fields.Selection(PRINTER_DRIVERS, string='Conexión', default='none', required=True)
    printer_host = fields.Char(string='IP de la impresora', help='IPv4 privada, p. ej. 192.168.0.61.')
    printer_port = fields.Integer(string='Puerto')
    camera_url = fields.Char(string='URL de la cámara', help='Flujo MJPEG en la misma IP de la impresora.')
    bridge_id = fields.Many2one('imago.printer.bridge', string='Puente', ondelete='restrict')
    live_status_id = fields.Many2one(
        'imago.printer.status', string='Estado en vivo', compute='_compute_live_status')
    live_state = fields.Selection(LIVE_STATES, string='Estado de la impresora', compute='_compute_live_status')

    _sql_constraints = [
        ('printer_port_range', 'CHECK(printer_port IS NULL OR (printer_port >= 0 AND printer_port <= 65535))',
         'El puerto debe estar entre 1 y 65535.'),
    ]

    def _compute_live_status(self):
        statuses = self.env['imago.printer.status'].sudo().search([('workcenter_id', 'in', self.ids)])
        by_workcenter = {status.workcenter_id.id: status for status in statuses}
        for workcenter in self:
            status = by_workcenter.get(workcenter.id, self.env['imago.printer.status'])
            workcenter.live_status_id = status
            workcenter.live_state = workcenter._live_state_of(status)

    def _live_state_of(self, status):
        self.ensure_one()
        if self.printer_driver == 'none' or not self.printer_host:
            return 'no_link'
        if not status or status.is_stale:
            return 'stale'
        return status.state

    @api.onchange('printer_driver', 'printer_host')
    def _onchange_printer_driver(self):
        if self.printer_driver in DEFAULT_PORTS and not self.printer_port:
            self.printer_port = DEFAULT_PORTS[self.printer_driver]
        template = DEFAULT_CAMERA.get(self.printer_driver)
        if template and self.printer_host and not self.camera_url:
            self.camera_url = template % self.printer_host.strip()

    @api.constrains('printer_driver', 'printer_host', 'printer_port', 'camera_url', 'bridge_id')
    def _check_printer_link(self):
        for workcenter in self:
            if workcenter.printer_driver == 'none':
                continue
            host = (workcenter.printer_host or '').strip()
            if not is_private_ipv4(host):
                raise ValidationError(_('La IP de %s debe ser una IPv4 privada (p. ej. 192.168.0.61), sin nombres '
                                        'de dominio.') % workcenter.display_name)
            if not 0 < (workcenter.printer_port or 0) <= 65535:
                raise ValidationError(_('Indica el puerto de %s.') % workcenter.display_name)
            if not workcenter.bridge_id:
                raise ValidationError(_('Elige el puente que lee %s.') % workcenter.display_name)
            workcenter._check_camera_url(host)
            workcenter._check_unique_link(host)

    def _check_camera_url(self, host):
        self.ensure_one()
        if not self.camera_url:
            return
        template = DEFAULT_CAMERA.get(self.printer_driver)
        parts = urlsplit(self.camera_url.strip())
        # Only the driver's own camera endpoint: the bridge must not be pointed at other ports/paths.
        if not template or parts.hostname != host or self.camera_url.strip() != template % host:
            raise ValidationError(_('La cámara de %(printer)s debe ser %(url)s (o déjala vacía).',
                                    printer=self.display_name,
                                    url=template % host if template else _('ninguna para este modelo')))

    def _check_unique_link(self, host):
        self.ensure_one()
        duplicate = self.search([
            ('id', '!=', self.id), ('printer_driver', '!=', 'none'),
            ('printer_host', '=', host), ('printer_port', '=', self.printer_port),
        ], limit=1)
        if duplicate:
            raise ValidationError(_('%(a)s y %(b)s no pueden usar la misma IP y puerto.',
                                    a=self.display_name, b=duplicate.display_name))

    @api.model_create_multi
    def create(self, vals_list):
        workcenters = super().create(vals_list)
        workcenters.mapped('bridge_id')._bump_config_version()
        return workcenters

    def write(self, vals):
        old_bridges = self.mapped('bridge_id') if set(vals) & set(LINK_FIELDS) else self.env['imago.printer.bridge']
        result = super().write(vals)
        if set(vals) & set(LINK_FIELDS):
            (old_bridges | self.mapped('bridge_id'))._bump_config_version()
        return result
