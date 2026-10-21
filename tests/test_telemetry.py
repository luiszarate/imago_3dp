# -*- coding: utf-8 -*-
import base64
import io
from datetime import timedelta

from PIL import Image

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import Form, new_test_user

from .common import Imago3dpCommon


def _jpeg():
    buffer = io.BytesIO()
    Image.new('RGB', (8, 6), (120, 60, 30)).save(buffer, format='JPEG')
    return buffer.getvalue()


JPEG = _jpeg()
SECRET = 'not-a-real-wifi-password'


@tagged('post_install', '-at_install')
class TestTelemetry(Imago3dpCommon):
    """SPEC 16 F2/F3: printer link, bridge API, live status, events and alerts."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bridge_user = new_test_user(cls.env, login='bridge_tech', name='Puente técnico',
                                        groups='base.group_portal,imago_3dp.group_print_bridge')
        cls.bridge = cls.env['imago.printer.bridge'].create({'name': 'Puente planta', 'user_id': cls.bridge_user.id})
        cls.printer1.write({'printer_driver': 'creality_box', 'printer_host': '192.168.0.248', 'printer_port': 81,
                            'bridge_id': cls.bridge.id})
        cls.printer2.write({'printer_driver': 'flashforge_tcp', 'printer_host': '192.168.0.61', 'printer_port': 8899,
                            'camera_url': 'http://192.168.0.61:8080/?action=stream', 'bridge_id': cls.bridge.id})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _item(self, printer, state='idle', **values):
        item = {'workcenter_id': printer.id, 'reachable': True, 'state': state}
        item.update(values)
        return item

    def _push(self, items, sent_at=None, user=None):
        # Each test push is a new bridge cycle (the API rejects pushes closer than 3 s).
        self.bridge.write({'last_seen': fields.Datetime.now() - timedelta(seconds=30)})
        payload = {
            'bridge_version': '0.2.0',
            'sent_at': (sent_at or fields.Datetime.now()).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'printers': items,
        }
        return self.env['imago.printer.bridge'].with_user(user or self.bridge_user).push_telemetry(payload)

    def _status(self, printer):
        return self.env['imago.printer.status'].search([('workcenter_id', '=', printer.id)])

    def _age(self, status, **delta):
        moment = fields.Datetime.now() - timedelta(**delta)
        status.write({'received_at': moment, 'state_since': moment})

    def _events(self, printer, event_type, open_only=False):
        domain = [('workcenter_id', '=', printer.id), ('event_type', '=', event_type)]
        if open_only:
            domain.append(('alert_open', '=', True))
        return self.env['imago.printer.event'].search(domain)

    # ------------------------------------------------------------------
    # A-20 / A-29 printer link
    # ------------------------------------------------------------------
    def test_a20_printer_host_must_be_private_ipv4(self):
        for host in ('impresora.local', '8.8.8.8', '127.0.0.1', '169.254.10.1', '10.0.0'):
            with self.assertRaises(ValidationError, msg=host):
                self.printer1.write({'printer_host': host})
        with self.assertRaises(ValidationError):
            self.printer2.write({'camera_url': 'http://192.168.0.99:8080/?action=stream'})
        with self.assertRaises(ValidationError):
            self.printer2.write({'printer_host': '192.168.0.248', 'printer_port': 81,
                                 'camera_url': False})

    def test_a20_driver_proposes_port_and_camera(self):
        printer = self.env['mrp.workcenter'].create({'name': '3DP-09', 'code': '3DP-09', 'is_3d_printer': True})
        form = Form(printer)
        form.printer_driver = 'flashforge_tcp'
        form.printer_host = '192.168.0.70'
        self.assertEqual(form.printer_port, 8899)
        self.assertEqual(form.camera_url, 'http://192.168.0.70:8080/?action=stream')

    def test_a29_link_change_bumps_config_version(self):
        version = self.bridge.config_version
        self.printer1.write({'printer_host': '192.168.0.250'})
        self.assertGreater(self.bridge.config_version, version)
        self.assertEqual(self._push([])['config_version'], self.bridge.config_version)

    # ------------------------------------------------------------------
    # A-21 … A-23, A-28 bridge API
    # ------------------------------------------------------------------
    def test_a21_only_the_bridge_user_can_use_the_api(self):
        config = self.env['imago.printer.bridge'].with_user(self.bridge_user).get_config()
        printers = {p['workcenter_id']: p for p in config['printers']}
        self.assertEqual(printers[self.printer1.id]['driver'], 'creality_box')
        self.assertEqual(printers[self.printer2.id]['camera_url'], 'http://192.168.0.61:8080/?action=stream')
        self.assertEqual(config['config_version'], self.bridge.config_version)
        for user in (self.operator, self.manager, self.requester):
            with self.assertRaises(AccessError):
                self.env['imago.printer.bridge'].with_user(user).get_config()
            with self.assertRaises(AccessError):
                self._push([], user=user)

    def test_a22_invalid_entries_do_not_block_valid_ones(self):
        other = self.env['mrp.workcenter'].create({'name': 'Otra', 'code': 'X', 'is_3d_printer': True})
        result = self._push([
            self._item(other),
            self._item(self.printer1, nozzle_temp=900),
            self._item(self.printer2, 'printing', progress=42.0, nozzle_temp=240, nozzle_target=240,
                       layer=48, layer_total=94, file_name='Cabezal.gx'),
        ])
        self.assertTrue(result['ok'])
        self.assertEqual({e['error'] for e in result['errors']}, {'workcenter_id', 'nozzle_temp'})
        status = self._status(self.printer2)
        self.assertEqual((status.state, status.progress, status.layer, status.file_name),
                         ('printing', 42.0, 48, 'Cabezal.gx'))
        self.assertFalse(self._status(self.printer1))

    def test_a23_unknown_keys_are_rejected_and_never_stored(self):
        result = self._push([self._item(self.printer1, wifipasswd=SECRET)])
        self.assertEqual(result['errors'], [{'workcenter_id': self.printer1.id, 'error': 'unknown_keys:wifipasswd'}])
        self.assertNotIn(SECRET, str(result))
        self.assertFalse(self._status(self.printer1))
        stored = self.env['imago.printer.status'].search([]).read()
        self.assertNotIn(SECRET, str(stored))

    def test_a28_bad_snapshot_is_dropped_but_status_kept(self):
        result = self._push([self._item(self.printer2, snapshot_jpeg_b64=base64.b64encode(b'GIF89a').decode())])
        self.assertEqual(result['errors'], [{'workcenter_id': self.printer2.id, 'error': 'snapshot_rejected'}])
        status = self._status(self.printer2)
        self.assertEqual(status.state, 'idle')
        self.assertFalse(status.snapshot)
        big = base64.b64encode(b'\xff\xd8' + b'0' * (600 * 1024)).decode()
        self.assertEqual(self._push([self._item(self.printer2, snapshot_jpeg_b64=big)])['errors'][0]['error'],
                         'snapshot_rejected')
        self._push([self._item(self.printer2, snapshot_jpeg_b64=base64.b64encode(JPEG).decode())])
        self.assertEqual(base64.b64decode(status.snapshot), JPEG)

    def test_hostile_values_never_break_the_batch(self):
        result = self._push([
            self._item(self.printer1, progress=float('nan')),
            {'workcenter_id': [self.printer2.id], 'state': 'idle'},
            self._item(self.printer2, layer=10 ** 9),
        ])
        self.assertTrue(result['ok'])
        self.assertEqual([e['error'] for e in result['errors']], ['progress', 'workcenter_id', 'layer'])
        result = self._push([self._item(self.printer2, file_name='ok\u202e\x1b[31mfake.gx\x00'),
                             self._item(self.printer2)])
        self.assertEqual(result['errors'], [{'workcenter_id': self.printer2.id, 'error': 'duplicate'}])
        self.assertEqual(self._status(self.printer2).file_name, 'ok[31mfake.gx')
        too_many = self._push([self._item(self.printer1)] * 5)
        self.assertEqual(too_many['error'], 'too_many_printers')
        fake_jpeg = base64.b64encode(b'\xff\xd8' + b'0' * 64 + b'\xff\xd9').decode()
        self.assertEqual(self._push([self._item(self.printer2, snapshot_jpeg_b64=fake_jpeg)])['errors'][0]['error'],
                         'snapshot_rejected')

    def test_promoted_technical_user_loses_api_access(self):
        self.bridge_user.write({'groups_id': [(3, self.env.ref('base.group_portal').id),
                                              (4, self.env.ref('base.group_user').id)]})
        with self.assertRaises(AccessError):
            self.env['imago.printer.bridge'].with_user(self.bridge_user).get_config()

    def test_camera_must_be_the_driver_endpoint(self):
        with self.assertRaises(ValidationError):
            self.printer2.write({'camera_url': 'http://192.168.0.61:22/'})
        with self.assertRaises(ValidationError):
            self.printer1.write({'camera_url': 'http://192.168.0.248:8080/?action=stream'})

    def test_alert_cooldown_after_flapping(self):
        self._push([self._item(self.printer2, 'error', error_text='Termistor')])
        self._push([self._item(self.printer2, 'idle')])
        self._push([self._item(self.printer2, 'error', error_text='Termistor')])
        self.assertEqual(len(self._events(self.printer2, 'error').filtered('is_alert')), 1)
        self.assertFalse(self._events(self.printer2, 'error', open_only=True))

    def test_rate_limit_and_clock_skew(self):
        self.assertTrue(self._push([self._item(self.printer1)])['ok'])
        payload = {'sent_at': fields.Datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'), 'printers': []}
        again = self.env['imago.printer.bridge'].with_user(self.bridge_user).push_telemetry(payload)
        self.assertEqual(again['error'], 'rate_limited')
        future = self._push([self._item(self.printer1)], sent_at=fields.Datetime.now() + timedelta(minutes=10))
        self.assertEqual(future['error'], 'clock_skew')

    def test_technical_user_must_be_portal_and_keys_are_admin_only(self):
        internal = new_test_user(self.env, login='bridge_internal', groups='base.group_user,imago_3dp.group_print_bridge')
        with self.assertRaises(ValidationError):
            self.env['imago.printer.bridge'].create({'name': 'Interno', 'user_id': internal.id})
        with self.assertRaises(AccessError):
            self.bridge.with_user(self.manager).action_generate_api_key()
        admin = new_test_user(self.env, login='access_admin', groups='base.group_user,base.group_erp_manager')
        action = self.bridge.with_user(admin).action_generate_api_key()
        key = action['context']['default_key']
        self.assertEqual(self.env['res.users.apikeys']._check_credentials(scope='rpc', key=key), self.bridge_user.id)
        self.assertEqual(self.bridge.api_key_count, 1)
        self.bridge.with_user(admin).action_revoke_api_keys()
        self.assertFalse(self.env['res.users.apikeys']._check_credentials(scope='rpc', key=key))
        with self.assertRaises(AccessError):
            self.env['imago.print.request'].with_user(self.bridge_user).search([])

    def test_status_and_events_cannot_be_written_by_operators(self):
        self._push([self._item(self.printer1)])
        status = self._status(self.printer1)
        with self.assertRaises(AccessError):
            status.with_user(self.operator).write({'state': 'printing'})
        with self.assertRaises(AccessError):
            self.env['imago.printer.event'].with_user(self.operator).create(
                {'workcenter_id': self.printer1.id, 'event_type': 'started'})

    # ------------------------------------------------------------------
    # A-26 / A-27 freshness and no business side effects
    # ------------------------------------------------------------------
    def test_a26_live_state_freshness(self):
        self.assertEqual(self.printer1.live_state, 'stale')
        self._push([self._item(self.printer1, 'printing')])
        self.printer1.invalidate_cache()
        self.assertEqual(self.printer1.live_state, 'printing')
        self._age(self._status(self.printer1), seconds=120)
        self.printer1.invalidate_cache()
        self.assertEqual(self.printer1.live_state, 'stale')
        self.printer1.write({'printer_driver': 'none'})
        self.printer1.invalidate_cache()
        self.assertEqual(self.printer1.live_state, 'no_link')

    def test_a27_telemetry_never_changes_business_data(self):
        request = self._submit_and_queue(self._create_request())
        job = self._start(request, lots=self.lot_abs_1)
        before = self._lot_qty(self.lot_abs_1)
        self._push([self._item(self.printer1, 'printing')])
        self._push([self._item(self.printer1, 'finished')])
        self.assertEqual(request.state, 'printing')
        self.assertEqual(job.result, 'running')
        self.assertEqual(self._lot_qty(self.lot_abs_1), before)

    # ------------------------------------------------------------------
    # A-24 / A-25 events and alerts
    # ------------------------------------------------------------------
    def test_a24_transitions_and_finished_with_open_attempt(self):
        request = self._submit_and_queue(self._create_request())
        self._start(request, lots=self.lot_abs_1)
        self._push([self._item(self.printer1, 'idle')])
        self._push([self._item(self.printer1, 'printing')])
        self.assertEqual(len(self._events(self.printer1, 'started')), 1)
        self._push([self._item(self.printer1, 'finished')])
        self.assertEqual(len(self._events(self.printer1, 'finished')), 1)
        self.assertFalse(self._events(self.printer1, 'finished_open'))

        status = self._status(self.printer1)
        status.write({'state_since': fields.Datetime.now() - timedelta(minutes=10)})
        self.env['imago.printer.status']._cron_check_alerts()
        self.env['imago.printer.status']._cron_check_alerts()
        alert = self._events(self.printer1, 'finished_open', open_only=True)
        self.assertEqual(len(alert), 1)
        self.assertEqual(alert.activity_id.res_model, 'imago.print.request')
        self.assertEqual(alert.activity_id.res_id, request.id)

        self._finish(request, 'ok', [(self.lot_abs_1, 50.0)])
        self.env['imago.printer.status']._cron_check_alerts()
        self.assertFalse(self._events(self.printer1, 'finished_open', open_only=True))
        self.assertFalse(alert.activity_id.exists())

    def test_a24_preheating_idle_is_not_a_finished_print(self):
        request = self._submit_and_queue(self._create_request())
        self._start(request, lots=self.lot_abs_1)
        self._push([self._item(self.printer1, 'idle', nozzle_temp=260)])
        status = self._status(self.printer1)
        status.write({'state_since': fields.Datetime.now() - timedelta(minutes=30)})
        self.env['imago.printer.status']._cron_check_alerts()
        self.assertFalse(self._events(self.printer1, 'finished_open'))

    def test_a25_unregistered_print_alert_closes_when_attempt_starts(self):
        self._push([self._item(self.printer1, 'printing', file_name='BASESE~1.GCO')])
        self._push([self._item(self.printer1, 'printing', file_name='BASESE~1.GCO')])
        alert = self._events(self.printer1, 'unregistered', open_only=True)
        self.assertEqual(len(alert), 1)
        self.assertEqual(alert.activity_id.user_id, self.operator)
        request = self._submit_and_queue(self._create_request())
        self._start(request, lots=self.lot_abs_1)
        self._push([self._item(self.printer1, 'printing')])
        self.assertFalse(self._events(self.printer1, 'unregistered', open_only=True))

    def test_error_and_offline_alerts(self):
        self._push([self._item(self.printer2, 'error', error_text='Termistor')])
        error = self._events(self.printer2, 'error', open_only=True)
        self.assertEqual(len(error), 1)
        self.assertEqual(error.details, 'Termistor')
        self._push([self._item(self.printer2, 'idle')])
        self.assertFalse(self._events(self.printer2, 'error', open_only=True))

        request = self._submit_and_queue(self._create_request(filament_product_id=self.filament_pla.id),
                                         printer=self.printer2)
        self._start(request, printer=self.printer2, lots=self.lot_pla_1)
        self._age(self._status(self.printer2), minutes=15)
        self.env['imago.printer.status']._cron_check_alerts()
        self.assertEqual(len(self._events(self.printer2, 'offline', open_only=True)), 1)
        self._push([self._item(self.printer2, 'printing')])
        self.assertFalse(self._events(self.printer2, 'offline', open_only=True))

    # ------------------------------------------------------------------
    # Real print time
    # ------------------------------------------------------------------
    def test_real_print_minutes_adjust_machine_time(self):
        request = self._submit_and_queue(self._create_request())
        job = self._start(request, lots=self.lot_abs_1)
        job.write({'date_start': fields.Datetime.now() - timedelta(minutes=90)})
        job.workorder_id.time_ids.write({'date_start': fields.Datetime.now() - timedelta(minutes=90)})
        form = Form(self.env['imago.print.job.finish.wizard'].with_user(self.operator).with_context(
            default_job_id=job.id))
        self.assertGreaterEqual(form.print_minutes, 89)
        with form.line_ids.edit(0) as line:
            line.grams = 50.0
        form.print_minutes = 45
        self.assertEqual(form.print_date_end, job.date_start + timedelta(minutes=45))
        form.print_date_end = job.date_start + timedelta(minutes=50)
        self.assertEqual(form.print_minutes, 50)
        form.print_minutes = 45
        form.save().action_finish()
        self.assertAlmostEqual(job.duration_minutes, 45.0, places=1)
        self.assertAlmostEqual(sum(job.workorder_id.time_ids.mapped('duration')), 45.0, places=1)

    def test_print_minutes_cannot_exceed_elapsed_time(self):
        request = self._submit_and_queue(self._create_request())
        self._start(request, lots=self.lot_abs_1)
        with self.assertRaises(UserError):
            self._finish_with_minutes(request, 600)

    def _finish_with_minutes(self, request, minutes):
        job = request.job_ids.filtered(lambda j: j.result == 'running')
        form = Form(self.env['imago.print.job.finish.wizard'].with_user(self.operator).with_context(
            default_job_id=job.id))
        with form.line_ids.edit(0) as line:
            line.grams = 40.0
        form.print_minutes = minutes
        form.save().action_finish()

    def test_print_minutes_prefilled_from_printer(self):
        request = self._submit_and_queue(self._create_request())
        job = self._start(request, lots=self.lot_abs_1)
        self._push([self._item(self.printer1, 'printing', job_time_min=37)])
        self.assertEqual(job._default_print_minutes(), 37)

    def test_creality_without_progress_is_not_zero_percent(self):
        self._push([self._item(self.printer1, 'printing', job_time_min=14)])
        status = self._status(self.printer1)
        self.assertFalse(status.progress_known)
        data = self.env['imago.print.dashboard'].with_user(self.operator).get_dashboard_data()
        card = next(c for c in data['printers'] if c['id'] == self.printer1.id)
        self.assertEqual(card['live']['state'], 'printing')
        self.assertIsNone(card['live']['progress'])
        self.assertEqual(card['live']['job_time_min'], 14)
