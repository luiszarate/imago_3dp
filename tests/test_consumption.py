# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import Form

from .common import Imago3dpCommon


@tagged('post_install', '-at_install')
class TestConsumption(Imago3dpCommon):

    # A-08 -------------------------------------------------------------
    def test_a08_failed_attempt_consumes_exact_grams(self):
        request = self._submit_and_queue(self._create_request())
        self._start(request, lots=self.lot_abs_1)
        job = self._finish(request, 'failed', [(self.lot_abs_1, 85.0)], reason='spaghetti')
        self.assertEqual(job.result, 'failed')
        self.assertEqual(job.failure_count, 1)
        self.assertAlmostEqual(self._lot_qty(self.lot_abs_1), 915.0)
        self.assertAlmostEqual(self.lot_abs_1.spool_remaining_g, 915.0)
        self.assertEqual(request.state, 'queued')
        self.assertAlmostEqual(request.grams_failed, 85.0)
        self.assertAlmostEqual(request.grams_total, 85.0)
        consumption = job.consumption_ids
        self.assertEqual(len(consumption), 1)
        move = consumption.stock_move_id
        self.assertEqual(move.state, 'done')
        self.assertEqual(move.raw_material_production_id, request.production_id)
        self.assertEqual(move.print_consumption_id, consumption)
        self.assertEqual(move.move_line_ids.lot_id, self.lot_abs_1)
        self.assertTrue(self.lot_abs_1.opened_date)
        self.assertEqual(self.lot_abs_1.spool_state, 'open')

    def test_failed_attempt_requires_reason(self):
        request = self._submit_and_queue(self._create_request())
        job = self._start(request, lots=self.lot_abs_1)
        with self.assertRaises(UserError), self.env.cr.savepoint():
            job.with_user(self.operator)._finish('failed', 0, [(self.lot_abs_1, 10.0)])
        with self.assertRaises(UserError), self.env.cr.savepoint():
            job.with_user(self.operator)._finish('failed', 0, [(self.lot_abs_1, 10.0)], failure_reason='other')
        with self.assertRaises(UserError), self.env.cr.savepoint():
            job.with_user(self.operator)._finish('ok', 1, [(self.lot_abs_1, 0.0)])
        self.assertEqual(job.result, 'running')

    # A-09 -------------------------------------------------------------
    def test_a09_runout_two_spools(self):
        request = self._submit_and_queue(self._create_request())
        self._start(request, lots=self.lot_abs_1)
        job = self._finish(request, 'ok', [(self.lot_abs_1, 70.0), (self.lot_abs_2, 45.5)])
        self.assertEqual(len(job.consumption_ids), 2)
        self.assertAlmostEqual(self._lot_qty(self.lot_abs_1), 930.0)
        self.assertAlmostEqual(self._lot_qty(self.lot_abs_2), 954.5)
        self.assertAlmostEqual(job.grams_total, 115.5)
        self.assertTrue(all(c.stock_move_id.state == 'done' for c in job.consumption_ids))

    def test_start_with_two_spools_multimaterial(self):
        request = self._submit_and_queue(self._create_request())
        job = self._start(request, lots=self.lot_abs_1 | self.lot_pla_1)
        self.assertEqual(job.consumption_ids.mapped('lot_id'), self.lot_abs_1 | self.lot_pla_1)
        self.assertTrue(all(c.grams == 0.0 for c in job.consumption_ids))
        # pre-filled lines; the unused spool (0 g) is dropped
        self._finish(request, 'ok', [(self.lot_abs_1, 30.0), (self.lot_pla_1, 0.0)])
        self.assertEqual(job.consumption_ids.lot_id, self.lot_abs_1)
        self.assertAlmostEqual(self._lot_qty(self.lot_pla_1), 1000.0)

    # A-10 -------------------------------------------------------------
    def test_a10_cannot_consume_more_than_available(self):
        request = self._submit_and_queue(self._create_request())
        job = self._start(request, lots=self.lot_abs_1)
        with self.assertRaises(UserError), self.env.cr.savepoint():
            job.with_user(self.operator)._finish('ok', 1, [(self.lot_abs_1, 1000.5)])
        job.invalidate_cache()
        self.assertEqual(job.result, 'running')
        self.assertAlmostEqual(self._lot_qty(self.lot_abs_1), 1000.0)
        # exactly the available quantity is fine
        job.with_user(self.operator)._finish('ok', 1, [(self.lot_abs_1, 1000.0)])
        self.assertAlmostEqual(self._lot_qty(self.lot_abs_1), 0.0)
        self.assertEqual(self.lot_abs_1.spool_state, 'empty')

    # A-13 -------------------------------------------------------------
    def _create_production_workorder(self, workcenter):
        part = self.env['product.product'].create({'name': 'Wing LH – costilla ABS', 'type': 'consu'})
        insert = self.env['product.product'].create({'name': 'Inserto roscado', 'type': 'consu'})
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': part.product_tmpl_id.id,
            'product_qty': 1,
            'consumption': 'strict',
            'bom_line_ids': [(0, 0, {'product_id': insert.id, 'product_qty': 1})],
            'operation_ids': [(0, 0, {'name': '70 [MCH] Imprimir componentes ABS',
                                      'workcenter_id': workcenter.id, 'time_cycle_manual': 60})],
        })
        mo_form = Form(self.env['mrp.production'])
        mo_form.product_id = part
        mo_form.bom_id = bom
        production = mo_form.save()
        production.action_confirm()
        return production

    def test_a13_production_workorder_filament(self):
        production = self._create_production_workorder(self.printer1)
        workorder = production.workorder_ids
        workorder.button_start()
        action = workorder.with_user(self.operator).action_open_filament_wizard()
        form = Form(self.env[action['res_model']].with_user(self.operator).with_context(action['context']))
        with form.line_ids.new() as line:
            line.lot_id = self.lot_abs_1
            line.grams = 40.0
        form.save().action_confirm()
        self.assertAlmostEqual(self._lot_qty(self.lot_abs_1), 960.0)
        consumption = workorder.print_consumption_ids
        self.assertEqual(len(consumption), 1)
        self.assertEqual(consumption.source, 'production')
        self.assertEqual(consumption.production_id, production)
        self.assertEqual(consumption.workcenter_id, self.printer1)
        move = consumption.stock_move_id
        self.assertEqual(move.state, 'done')
        self.assertFalse(move.raw_material_production_id)
        self.assertEqual(move.origin, production.name)
        groups = self.env['imago.print.consumption'].read_group(
            [('id', '=', consumption.id)], ['grams'], ['source'])
        self.assertEqual(groups[0]['source'], 'production')
        self.assertAlmostEqual(groups[0]['grams'], 40.0)
        # The strict BOM MO still closes normally: the filament is not a raw move of it
        workorder.button_finish()
        production.qty_producing = 1
        production.move_raw_ids.quantity_done = 1
        production.button_mark_done()
        self.assertEqual(production.state, 'done')

    def test_filament_wizard_rejects_non_printer_workorder(self):
        production = self._create_production_workorder(self.labor_wc)
        wizard = self.env['imago.workorder.filament.wizard'].with_user(self.operator).create({
            'workorder_id': production.workorder_ids.id,
            'line_ids': [(0, 0, {'lot_id': self.lot_abs_1.id, 'grams': 10.0})],
        })
        with self.assertRaises(UserError):
            wizard.action_confirm()

    # A-17 -------------------------------------------------------------
    def test_a17_reports_group_by_material_purpose_month_and_failure_rate(self):
        request_a = self._submit_and_queue(self._create_request())
        self._start(request_a, lots=self.lot_abs_1)
        self._finish(request_a, 'failed', [(self.lot_abs_1, 25.0)], reason='clog')
        self._start(request_a, lots=self.lot_abs_1)
        self._finish(request_a, 'ok', [(self.lot_abs_1, 30.0)])
        request_b = self._submit_and_queue(
            self._create_request(purpose_id=self.purpose_tooling.id, filament_product_id=self.filament_pla.id),
            printer=self.printer2)
        self._start(request_b, printer=self.printer2, lots=self.lot_pla_1)
        self._finish(request_b, 'ok', [(self.lot_pla_1, 12.0)])

        Consumption = self.env['imago.print.consumption'].with_user(self.operator)
        by_material = Consumption.read_group([], ['grams'], ['material_id'])
        grams_by_material = {g['material_id'][0]: g['grams'] for g in by_material}
        self.assertAlmostEqual(grams_by_material[self.mat_abs.id], 55.0)
        self.assertAlmostEqual(grams_by_material[self.mat_pla.id], 12.0)
        by_purpose = Consumption.read_group([], ['grams'], ['purpose_id'])
        grams_by_purpose = {g['purpose_id'][0]: g['grams'] for g in by_purpose}
        self.assertAlmostEqual(grams_by_purpose[self.purpose.id], 55.0)
        self.assertAlmostEqual(grams_by_purpose[self.purpose_tooling.id], 12.0)
        by_month = Consumption.read_group([], ['grams'], ['date:month'])
        self.assertEqual(len(by_month), 1)
        self.assertAlmostEqual(by_month[0]['grams'], 67.0)

        Job = self.env['imago.print.job'].with_user(self.operator)
        rate = Job.read_group([], ['failure_count'], ['workcenter_id', 'result'], lazy=False)
        cells = {(g['workcenter_id'][0], g['result']): g['__count'] for g in rate}
        self.assertEqual(cells[(self.printer1.id, 'failed')], 1)
        self.assertEqual(cells[(self.printer1.id, 'ok')], 1)
        self.assertEqual(cells[(self.printer2.id, 'ok')], 1)
        per_printer = Job.read_group([], ['failure_count'], ['workcenter_id'])
        failures = {g['workcenter_id'][0]: (g['failure_count'], g['workcenter_id_count']) for g in per_printer}
        self.assertEqual(failures[self.printer1.id], (1, 2))
        self.assertEqual(failures[self.printer2.id], (0, 1))

    # Review hardening ---------------------------------------------------
    def test_production_wizard_refused_on_request_workorder(self):
        request = self._submit_and_queue(self._create_request())
        job = self._start(request, lots=self.lot_abs_1)
        self.assertTrue(job.workorder_id.is_print_request_wo)
        wizard = self.env['imago.workorder.filament.wizard'].with_user(self.operator).create({
            'workorder_id': job.workorder_id.id,
            'line_ids': [(0, 0, {'lot_id': self.lot_abs_1.id, 'grams': 10.0})],
        })
        with self.assertRaises(UserError):
            wizard.action_confirm()
        self.assertAlmostEqual(self._lot_qty(self.lot_abs_1), 1000.0)

    def test_posted_consumption_is_locked(self):
        request = self._submit_and_queue(self._create_request())
        self._start(request, lots=self.lot_abs_1)
        job = self._finish(request, 'ok', [(self.lot_abs_1, 30.0)])
        consumption = job.consumption_ids.with_user(self.operator)
        with self.assertRaises(UserError):
            consumption.write({'grams': 5.0})
        with self.assertRaises(UserError):
            consumption.with_user(self.manager).unlink()
        with self.assertRaises(UserError):
            job.with_user(self.manager).unlink()
        with self.assertRaises(UserError):
            request.with_user(self.manager).unlink()

    def test_ok_attempt_requires_pieces(self):
        request = self._submit_and_queue(self._create_request())
        job = self._start(request, lots=self.lot_abs_1)
        with self.assertRaises(UserError), self.env.cr.savepoint():
            job.with_user(self.operator)._finish('ok', 0, [(self.lot_abs_1, 10.0)])
        self.assertEqual(job.result, 'running')

    def test_labor_without_workcenter_fails_before_stock(self):
        self.company.print3d_labor_workcenter_id = False
        request = self._submit_and_queue(self._create_request())
        job = self._start(request, lots=self.lot_abs_1)
        with self.assertRaises(UserError), self.env.cr.savepoint():
            job.with_user(self.operator)._finish('ok', 1, [(self.lot_abs_1, 10.0)], labor_minutes=15)
        self.assertAlmostEqual(self._lot_qty(self.lot_abs_1), 1000.0)

    def test_spool_in_sublocation(self):
        shelf = self.env['stock.location'].create({
            'name': 'Estante A', 'location_id': self.location_3dp.id, 'usage': 'internal'})
        lot = self._create_spool(self.filament_abs, 0.0)
        self.env['stock.quant']._update_available_quantity(self.filament_abs, shelf, 300.0, lot_id=lot)
        self.env['stock.quant']._update_available_quantity(self.filament_abs, self.location_3dp, 100.0, lot_id=lot)
        self.assertAlmostEqual(lot.spool_remaining_g, 400.0)
        request = self._submit_and_queue(self._create_request())
        self._start(request, lots=lot)
        job = self._finish(request, 'ok', [(lot, 350.0)])
        self.assertEqual(len(job.consumption_ids.stock_move_id.move_line_ids), 2)
        self.assertAlmostEqual(self._lot_qty(lot), 50.0)
        # weighing a spool split over two locations leaves the total on one line
        self.env['imago.spool.weigh.wizard'].with_user(self.operator).create({
            'lot_id': lot.id, 'gross_weight_g': 450.0, 'tare_g': 250.0}).action_confirm()
        self.assertAlmostEqual(self._lot_qty(lot), 200.0)
