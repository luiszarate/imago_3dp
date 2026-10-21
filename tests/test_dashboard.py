# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import Imago3dpCommon


@tagged('post_install', '-at_install')
class TestDashboard(Imago3dpCommon):
    """SPEC 16.10 / A-19: operator dashboard (phase F1, Odoo data only)."""

    def _data(self, user=None, **kwargs):
        return self.env['imago.print.dashboard'].with_user(user or self.operator).get_dashboard_data(**kwargs)

    def _printer_card(self, data, printer):
        return next(card for card in data['printers'] if card['id'] == printer.id)

    def test_a19_action_and_menu(self):
        action = self.env.ref('imago_3dp.action_print_dashboard')
        self.assertEqual(action.tag, 'imago_3dp_dashboard')
        menu = self.env.ref('imago_3dp.menu_print3d_dashboard')
        self.assertEqual(menu.action, action)
        self.assertIn(self.env.ref('imago_3dp.group_print_operator'), menu.groups_id)

    def test_a19_requester_cannot_read_dashboard(self):
        with self.assertRaises(AccessError):
            self._data(user=self.requester)

    def test_a19_operator_gets_printers_queue_alerts_kpis(self):
        queued = self._submit_and_queue(self._create_request(title='Pieza en cola'))
        submitted = self._create_request(title='Pieza enviada')
        submitted.with_user(self.requester).action_submit()

        data = self._data()

        self.assertEqual(set(data), {'generated_at', 'kpis', 'actions', 'printers', 'queue', 'spools', 'charts'})
        self.assertEqual({card['id'] for card in data['printers']}, {self.printer1.id, self.printer2.id})
        card = self._printer_card(data, self.printer1)
        self.assertEqual(card['status'], 'free')
        self.assertFalse(card['job'])
        self.assertEqual([row['id'] for row in data['queue']], [queued.id, submitted.id])
        self.assertEqual(data['kpis']['queued'], 1)
        self.assertEqual(data['kpis']['submitted'], 1)
        self.assertEqual(data['kpis']['printers'], 2)
        self.assertEqual(data['kpis']['printing'], 0)

    def test_dashboard_without_charts(self):
        data = self._data(include_charts=False)
        self.assertNotIn('charts', data)
        self.assertIn('printers', data)

    def test_dashboard_printing_card_and_spool_warning(self):
        request = self._submit_and_queue(self._create_request(), est_grams=1500.0, est_minutes=120)
        job = self._start(request, lots=self.lot_abs_1)

        data = self._data()

        card = self._printer_card(data, self.printer1)
        self.assertEqual(card['status'], 'printing')
        self.assertEqual(card['request']['id'], request.id)
        self.assertEqual(card['job']['id'], job.id)
        self.assertTrue(0.0 <= card['job']['progress_est'] <= 99.0)
        self.assertEqual(card['spool']['id'], self.lot_abs_1.id)
        self.assertAlmostEqual(card['spool']['remaining_g'], 1000.0)
        # The attempt expects 1500 g but the mounted spool has 1000 g.
        self.assertTrue(card['filament_warning'])
        self.assertEqual(data['kpis']['printing'], 1)
        self.assertTrue(any(action['kind'] == 'filament' for action in data['actions']))

    def test_dashboard_late_request_and_low_spool(self):
        request = self._submit_and_queue(self._create_request())
        request.sudo().write({'date_required': fields.Date.today() - timedelta(days=2)})
        low_lot = self._create_spool(self.filament_abs, 100.0)
        self.printer2._mount_lot(low_lot)

        data = self._data()

        self.assertEqual(data['kpis']['late'], 1)
        self.assertTrue(next(row for row in data['queue'] if row['id'] == request.id)['is_late'])
        self.assertGreaterEqual(data['kpis']['low_spools'], 1)
        kinds = {action['kind'] for action in data['actions']}
        self.assertIn('late', kinds)
        self.assertIn('spool', kinds)
        # Critical actions come first.
        self.assertEqual(data['actions'][0]['severity'], 'critical')

    def test_dashboard_out_of_service_alert(self):
        self.printer2.with_user(self.operator).action_toggle_out_of_service()
        data = self._data()
        self.assertEqual(self._printer_card(data, self.printer2)['status'], 'out_of_service')

    def test_dashboard_charts_and_failure_rate(self):
        failed = self._submit_and_queue(self._create_request(title='Falla'))
        self._start(failed, lots=self.lot_abs_1)
        self._finish(failed, 'failed', [(self.lot_abs_1, 85.0)], pieces_ok=0, reason='adhesion')
        ok = self._submit_and_queue(self._create_request(title='Correcta', purpose_id=self.purpose_tooling.id))
        self._start(ok, lots=self.lot_abs_2)
        self._finish(ok, 'ok', [(self.lot_abs_2, 40.0)])

        data = self._data()
        charts = data['charts']

        self.assertEqual(data['kpis']['failure_rate_7d'], 50.0)
        self.assertEqual(data['kpis']['jobs_7d'], 2)
        pareto = {row['reason']: row['count'] for row in charts['failure_pareto']}
        self.assertEqual(pareto, {'adhesion': 1})
        printer_row = next(row for row in charts['success_by_printer'] if row['id'] == self.printer1.id)
        self.assertEqual((printer_row['ok'], printer_row['partial'], printer_row['failed']), (1, 0, 1))
        grams = sum(sum(series['data']) for series in charts['grams_by_purpose']['series'])
        self.assertAlmostEqual(grams, 125.0)
        self.assertEqual(len(charts['grams_by_purpose']['weeks']), 8)
        occupancy = next(row for row in charts['occupancy'] if row['id'] == self.printer1.id)
        self.assertGreaterEqual(occupancy['hours'], 0.0)
        self.assertTrue(0.0 <= occupancy['pct'] <= 100.0)

    def test_dashboard_free_printer_with_queue_and_review_actions(self):
        queued = self._submit_and_queue(self._create_request(title='Siguiente'), printer=self.printer2)
        submitted = self._create_request(title='Nueva')
        submitted.with_user(self.requester).action_submit()

        actions = {action['kind']: action for action in self._data()['actions']}

        self.assertEqual(actions['idle']['button']['method'], 'action_open_start_wizard')
        self.assertEqual(actions['idle']['severity'], 'info')
        self.assertEqual(actions['idle']['button']['id'], queued.id)
        self.assertEqual(actions['review']['open']['id'], submitted.id)

    def test_dashboard_overdue_attempt_asks_to_finish(self):
        request = self._submit_and_queue(self._create_request(), est_minutes=30)
        job = self._start(request, lots=self.lot_abs_1)
        job.write({'date_start': fields.Datetime.now() - timedelta(minutes=45)})

        data = self._data()

        self.assertTrue(self._printer_card(data, self.printer1)['job']['overdue'])
        overdue = next(action for action in data['actions'] if action['kind'] == 'overdue')
        self.assertEqual(overdue['button']['method'], 'action_open_finish_wizard')
        self.assertEqual(overdue['button']['id'], request.id)

    def test_dashboard_queue_includes_post_process_and_stamps(self):
        request = self._submit_and_queue(self._create_request(title='Terminada'))
        self._start(request, lots=self.lot_abs_1)
        self._finish(request, 'ok', [(self.lot_abs_1, 50.0)])
        self.assertEqual(request.state, 'post')

        data = self._data()

        row = next(row for row in data['queue'] if row['id'] == request.id)
        self.assertEqual(row['state'], 'post')
        self.assertEqual(data['kpis']['post'], 1)
        stamps = self._printer_card(data, self.printer1)['recent_jobs']
        self.assertEqual([stamp['result'] for stamp in stamps], ['ok'])
        self.assertTrue(any(action['kind'] == 'deliver' for action in data['actions']))

    def test_dashboard_idle_printer_ranks_before_deliveries(self):
        done = self._submit_and_queue(self._create_request(title='Lista'))
        self._start(done, lots=self.lot_abs_1)
        self._finish(done, 'ok', [(self.lot_abs_1, 50.0)])
        self._submit_and_queue(self._create_request(title='Espera'), printer=self.printer2)

        kinds = [action['kind'] for action in self._data()['actions']]

        self.assertLess(kinds.index('idle'), kinds.index('deliver'))

    def test_dashboard_late_action_uses_short_date(self):
        request = self._submit_and_queue(self._create_request())
        late_day = fields.Date.today() - timedelta(days=2)
        request.sudo().write({'date_required': late_day})
        late = next(action for action in self._data()['actions'] if action['kind'] == 'late')
        self.assertIn(late_day.strftime('%d/%m'), late['detail'])

    def test_dashboard_spool_summary_and_critical_list(self):
        low_lot = self._create_spool(self.filament_pla, 90.0)
        self.printer1._mount_lot(self.lot_abs_1)

        spools = self._data()['spools']

        summary = {row['product_id']: row for row in spools['summary']}
        self.assertEqual(summary[self.filament_abs.id]['spools'], 2)
        self.assertEqual(summary[self.filament_abs.id]['grams'], 2000)
        self.assertEqual(summary[self.filament_pla.id]['low'], 1)
        critical = {row['id']: row for row in spools['critical']}
        self.assertIn(low_lot.id, critical)
        self.assertEqual(critical[self.lot_abs_1.id]['printer'], self.printer1.name)
        self.assertNotIn(self.lot_abs_2.id, critical)
        self.assertEqual(spools['critical'][0]['id'], low_lot.id)
