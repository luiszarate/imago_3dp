# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import Form

from .common import Imago3dpCommon


@tagged('post_install', '-at_install')
class TestCombinedPrint(Imago3dpCommon):
    """SPEC 17 / A-31…A-43: several requests printed on one plate."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _queued(self, title, est_grams, printer=None, **values):
        return self._submit_and_queue(self._create_request(title=title, **values), printer=printer,
                                      est_grams=est_grams)

    def _start_combined(self, lead, extras, printer=None, lots=None, est_minutes=120, user=None):
        wizard_model = self.env['imago.print.job.start.wizard'].with_user(user or self.operator).with_context(
            default_request_id=lead.id)
        form = Form(wizard_model)
        if printer:
            form.workcenter_id = printer
        if lots is not None:
            form.lot_ids.clear()
            for lot in lots:
                form.lot_ids.add(lot)
        for extra in extras:
            form.extra_request_ids.add(extra)
        form.est_minutes = est_minutes
        form.save().action_start()
        return lead.job_ids.filtered(lambda j: j.result == 'running').batch_id

    def _finish_combined(self, batch, plate_result, lots, results=None, shares=None, labor=0, reason=False):
        """``lots``: list of (lot, grams); ``results``: {request: (result, pieces_ok)};
        ``shares``: {request: pct}."""
        action = batch.lead_job_id.request_id.with_user(self.operator).action_open_finish_wizard()
        self.assertEqual(action['res_model'], 'imago.print.batch.finish.wizard')
        form = Form(self.env[action['res_model']].with_user(self.operator).with_context(**action['context']))
        form.plate_result = plate_result
        if reason:
            form.failure_reason = reason
        grams_by_lot = dict(lots)
        for index in range(len(form.lot_line_ids)):
            with form.lot_line_ids.edit(index) as line:
                line.grams = grams_by_lot.pop(line.lot_id, 0.0)
        for lot, grams in grams_by_lot.items():
            with form.lot_line_ids.new() as line:
                line.lot_id = lot
                line.grams = grams
        for index in range(len(form.request_line_ids)):
            with form.request_line_ids.edit(index) as line:
                request = line.request_id
                if results and request in results:
                    line.result, line.pieces_ok = results[request]
                    if line.result in ('partial', 'failed') and not line.failure_reason:
                        line.failure_reason = reason or 'adhesion'
                if shares and request in shares:
                    line.share_pct = shares[request]
        if labor:
            form.labor_minutes = labor
        form.save().action_finish()
        return batch

    def _job(self, request):
        return request.job_ids.sorted('id')[-1:]

    # ------------------------------------------------------------------
    # Start
    # ------------------------------------------------------------------
    def test_a31_start_combined_creates_one_machine_workorder(self):
        req_a = self._queued('Soporte A', 60.0)
        req_b = self._queued('Soporte B', 40.0)

        batch = self._start_combined(req_a, [req_b], lots=self.lot_abs_1)

        self.assertTrue(batch.name.startswith('PRB-'))
        self.assertEqual(batch.state, 'running')
        self.assertEqual(batch.request_ids, req_a | req_b)
        self.assertEqual(len(batch.job_ids), 2)
        self.assertTrue(all(job.result == 'running' for job in batch.job_ids))
        workorders = (req_a | req_b).mapped('production_id.workorder_ids').filtered(lambda w: w.state == 'progress')
        self.assertEqual(len(workorders), 1)
        self.assertEqual(workorders.production_id, req_a.production_id)
        self.assertEqual(batch.lead_job_id.request_id, req_a)
        self.assertFalse(self._job(req_b).workorder_id)
        self.assertEqual((req_a | req_b).mapped('state'), ['printing', 'printing'])
        self.printer1.invalidate_cache()
        self.assertEqual(self.printer1.printer_status, 'printing')

    def test_a32_cannot_combine_invalid_requests(self):
        req_a = self._queued('Soporte A', 60.0)
        draft = self._create_request(title='Borrador')
        with self.assertRaises(UserError):
            self._start_combined(req_a, [draft], lots=self.lot_abs_1)

        strict = self._queued('Sin sustitutos', 40.0, allow_substitute=False,
                              filament_product_id=self.filament_pla.id)
        with self.assertRaises(UserError):
            self._start_combined(req_a, [strict], lots=self.lot_abs_1)

        other = self._queued('Otra', 30.0)
        busy = self._queued('Ocupa la impresora', 30.0)
        self._start(busy, lots=self.lot_abs_2)
        with self.assertRaises(UserError):
            self._start_combined(req_a, [other], lots=self.lot_abs_1)

    def test_a32_cannot_combine_on_out_of_service_printer(self):
        req_a = self._queued('Soporte A', 60.0, printer=self.printer2,
                             filament_product_id=self.filament_pla.id)
        req_b = self._queued('Soporte B', 40.0, printer=self.printer2,
                             filament_product_id=self.filament_pla.id)
        self.printer2.with_user(self.operator).action_toggle_out_of_service()
        with self.assertRaises(UserError):
            self.env['imago.print.batch']._start_combined(
                req_a | req_b, self.printer2, self.lot_pla_1, est_minutes=60)

    def test_a33_default_share_follows_estimated_grams(self):
        req_a = self._queued('Soporte A', 60.0)
        req_b = self._queued('Soporte B', 40.0)
        batch = self._start_combined(req_a, [req_b], lots=self.lot_abs_1)
        self.assertAlmostEqual(self._job(req_a).share, 0.6)
        self.assertAlmostEqual(self._job(req_b).share, 0.4)

        req_c = self._queued('Sin estimado C', 0.0)
        req_d = self._queued('Sin estimado D', 0.0)
        batch_cd = self._start_combined(req_c, [req_d], printer=self.printer2, lots=self.lot_pla_1)
        self.assertEqual(batch_cd.job_ids.mapped('share'), [0.5, 0.5])

        with self.assertRaises(UserError):
            self._finish_combined(batch, 'ok', [(self.lot_abs_1, 100.0)], shares={req_a: 70.0, req_b: 40.0})

    # ------------------------------------------------------------------
    # Finish
    # ------------------------------------------------------------------
    def test_a34_grams_split_exactly_per_request_production(self):
        req_a = self._queued('Soporte A', 60.0)
        req_b = self._queued('Soporte B', 40.0)
        batch = self._start_combined(req_a, [req_b], lots=self.lot_abs_1)

        self._finish_combined(batch, 'ok', [(self.lot_abs_1, 100.0)])

        self.assertEqual(batch.state, 'done')
        self.assertAlmostEqual(self._lot_qty(self.lot_abs_1), 900.0)
        cons_a, cons_b = self._job(req_a).consumption_ids, self._job(req_b).consumption_ids
        self.assertAlmostEqual(cons_a.grams, 60.0)
        self.assertAlmostEqual(cons_b.grams, 40.0)
        self.assertEqual(cons_a.stock_move_id.raw_material_production_id, req_a.production_id)
        self.assertEqual(cons_b.stock_move_id.raw_material_production_id, req_b.production_id)

    def test_a34_three_equal_shares_sum_exactly(self):
        requests = [self._queued('Pieza %s' % n, 0.0) for n in range(3)]
        batch = self._start_combined(requests[0], requests[1:], lots=self.lot_abs_1)

        self._finish_combined(batch, 'ok', [(self.lot_abs_1, 100.0)])

        grams = [self._job(request).grams_total for request in requests]
        self.assertAlmostEqual(sum(grams), 100.0, places=6)
        self.assertAlmostEqual(self._lot_qty(self.lot_abs_1), 900.0)

    def test_a35_runout_two_spools_split_with_same_share(self):
        req_a = self._queued('Soporte A', 60.0)
        req_b = self._queued('Soporte B', 40.0)
        batch = self._start_combined(req_a, [req_b], lots=self.lot_abs_1)

        self._finish_combined(batch, 'ok', [(self.lot_abs_1, 70.0), (self.lot_abs_2, 30.0)])

        by_lot_a = {c.lot_id: c.grams for c in self._job(req_a).consumption_ids}
        by_lot_b = {c.lot_id: c.grams for c in self._job(req_b).consumption_ids}
        self.assertAlmostEqual(by_lot_a[self.lot_abs_1], 42.0)
        self.assertAlmostEqual(by_lot_a[self.lot_abs_2], 18.0)
        self.assertAlmostEqual(by_lot_b[self.lot_abs_1], 28.0)
        self.assertAlmostEqual(by_lot_b[self.lot_abs_2], 12.0)

    def test_a36_mixed_results_follow_each_request(self):
        req_a = self._queued('Soporte A', 60.0)
        req_b = self._queued('Soporte B', 40.0)
        batch = self._start_combined(req_a, [req_b], lots=self.lot_abs_1)

        self._finish_combined(batch, 'ok', [(self.lot_abs_1, 100.0)],
                              results={req_b: ('failed', 0)}, reason='spaghetti')

        self.assertEqual(req_a.state, 'post')
        self.assertEqual(req_b.state, 'queued')
        self.assertAlmostEqual(req_b.grams_failed, 40.0)
        self.assertAlmostEqual(req_a.grams_failed, 0.0)
        self.assertEqual(self._job(req_b).failure_reason, 'spaghetti')

    def test_v08_non_lead_request_production_can_be_closed(self):
        req_a = self._queued('Soporte A', 60.0)
        req_b = self._queued('Soporte B', 40.0)
        batch = self._start_combined(req_a, [req_b], lots=self.lot_abs_1)
        self._finish_combined(batch, 'ok', [(self.lot_abs_1, 100.0)])

        req_b.with_user(self.operator).action_deliver()
        self.assertEqual(req_b.state, 'done')
        self.assertEqual(req_b.production_id.state, 'done')
        req_a.with_user(self.operator).action_deliver()
        self.assertEqual(req_a.production_id.state, 'done')

    def test_v09_lead_request_delivered_first(self):
        req_a = self._queued('Soporte A', 60.0)
        req_b = self._queued('Soporte B', 40.0)
        batch = self._start_combined(req_a, [req_b], lots=self.lot_abs_1)
        self._finish_combined(batch, 'ok', [(self.lot_abs_1, 100.0)])

        req_a.with_user(self.operator).action_deliver()
        self.assertEqual(req_a.production_id.state, 'done')
        self.assertEqual(req_b.state, 'post')
        self.assertNotEqual(req_b.production_id.state, 'done')
        req_b.with_user(self.operator).action_deliver()
        self.assertEqual(req_b.production_id.state, 'done')

    def test_a37_machine_time_counted_once_and_split(self):
        req_a = self._queued('Soporte A', 60.0)
        req_b = self._queued('Soporte B', 40.0)
        batch = self._start_combined(req_a, [req_b], lots=self.lot_abs_1)
        self._finish_combined(batch, 'ok', [(self.lot_abs_1, 100.0)])

        logs = self.env['mrp.workcenter.productivity'].search([('workcenter_id', '=', self.printer1.id)])
        self.assertEqual(len(logs), 1)
        job_a, job_b = self._job(req_a), self._job(req_b)
        self.assertAlmostEqual(job_a.allocated_minutes, job_a.duration_minutes * 0.6)
        self.assertAlmostEqual(req_b.print_minutes_total, job_b.duration_minutes * 0.4)

    def test_a38_printer_indicators_count_plate_once(self):
        req_a = self._queued('Soporte A', 60.0)
        req_b = self._queued('Soporte B', 40.0)
        batch = self._start_combined(req_a, [req_b], lots=self.lot_abs_1)
        self._finish_combined(batch, 'failed', [(self.lot_abs_1, 100.0)],
                              results={req_a: ('failed', 0), req_b: ('failed', 0)}, reason='adhesion')

        printer_jobs = self.env['imago.print.job'].search(
            [('workcenter_id', '=', self.printer1.id), ('counts_for_printer', '=', True)])
        self.assertEqual(len(printer_jobs), 1)
        data = self.env['imago.print.dashboard'].with_user(self.operator).get_dashboard_data()
        self.assertEqual(data['kpis']['jobs_7d'], 1)
        self.assertEqual({row['reason']: row['count'] for row in data['charts']['failure_pareto']}, {'adhesion': 1})
        row = next(r for r in data['charts']['success_by_printer'] if r['id'] == self.printer1.id)
        self.assertEqual(row['failed'], 1)

    def test_a39_labor_minutes_split_per_request(self):
        req_a = self._queued('Soporte A', 60.0)
        req_b = self._queued('Soporte B', 40.0)
        batch = self._start_combined(req_a, [req_b], lots=self.lot_abs_1)

        self._finish_combined(batch, 'ok', [(self.lot_abs_1, 100.0)], labor=30)

        labor_a = self._job(req_a).labor_workorder_id
        labor_b = self._job(req_b).labor_workorder_id
        self.assertEqual(labor_a.production_id, req_a.production_id)
        self.assertEqual(labor_b.production_id, req_b.production_id)
        self.assertAlmostEqual(sum(labor_a.time_ids.mapped('duration')), 18.0, places=0)
        self.assertAlmostEqual(sum(labor_b.time_ids.mapped('duration')), 12.0, places=0)

    # ------------------------------------------------------------------
    # Guards, security, dashboard
    # ------------------------------------------------------------------
    def test_a40_cannot_cancel_or_finish_alone_while_running(self):
        req_a = self._queued('Soporte A', 60.0)
        req_b = self._queued('Soporte B', 40.0)
        batch = self._start_combined(req_a, [req_b], lots=self.lot_abs_1)

        with self.assertRaises(UserError):
            req_b.with_user(self.operator).action_cancel()
        with self.assertRaises(UserError):
            req_b.with_user(self.operator).action_reject()
        with self.assertRaises(UserError):
            self._finish(req_b, 'ok', [(self.lot_abs_1, 40.0)])

        self._finish_combined(batch, 'ok', [(self.lot_abs_1, 100.0)])
        req_b.with_user(self.operator).action_cancel()
        self.assertEqual(req_b.state, 'cancelled')

    def test_a41_requester_cannot_start_and_can_read(self):
        req_a = self._queued('Soporte A', 60.0)
        req_b = self._queued('Soporte B', 40.0)
        with self.assertRaises(AccessError):
            self.env['imago.print.batch'].with_user(self.requester)._start_combined(
                req_a | req_b, self.printer1, self.lot_abs_1, est_minutes=60)
        batch = self._start_combined(req_a, [req_b], lots=self.lot_abs_1)
        self.assertEqual(batch.with_user(self.requester).name, batch.name)
        with self.assertRaises(AccessError):
            batch.with_user(self.requester).write({'est_minutes': 1})

    def test_a42_dashboard_shows_combined_print(self):
        req_a = self._queued('Soporte A', 60.0)
        req_b = self._queued('Soporte B', 40.0)
        batch = self._start_combined(req_a, [req_b], lots=self.lot_abs_1, est_minutes=30)
        batch.lead_job_id.write({'date_start': batch.lead_job_id.date_start.replace(year=2020)})

        data = self.env['imago.print.dashboard'].with_user(self.operator).get_dashboard_data()

        card = next(c for c in data['printers'] if c['id'] == self.printer1.id)
        self.assertEqual(card['batch']['id'], batch.id)
        self.assertEqual([r['id'] for r in card['batch']['requests']], [req_a.id, req_b.id])
        overdue = [a for a in data['actions'] if a['kind'] == 'overdue']
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0]['button']['id'], req_a.id)

    def test_a43_single_attempts_keep_full_share(self):
        request = self._queued('Individual', 80.0)
        job = self._start(request, lots=self.lot_abs_1)
        self.assertFalse(job.batch_id)
        self.assertEqual(job.share, 1.0)
        self.assertTrue(job.counts_for_printer)
        self._finish(request, 'ok', [(self.lot_abs_1, 80.0)])
        self.assertAlmostEqual(job.allocated_minutes, job.duration_minutes)
