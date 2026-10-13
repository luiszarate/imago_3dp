# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import Imago3dpCommon


@tagged('post_install', '-at_install')
class TestSecurity(Imago3dpCommon):

    # A-05 -------------------------------------------------------------
    def test_a05_requester_cannot_edit_other_request(self):
        request = self._create_request()
        with self.assertRaises(AccessError):
            request.with_user(self.requester2).write({'title': 'Cambio ajeno'})
        # ...but can read it (transparent queue)
        self.assertEqual(request.with_user(self.requester2).title, 'Soporte de antena v3')

    def test_a05_requester_cannot_edit_own_request_once_queued(self):
        request = self._submit_and_queue(self._create_request())
        self.assertEqual(request.state, 'queued')
        with self.assertRaises(AccessError):
            request.with_user(self.requester).write({'title': 'Cambio tardío'})
        with self.assertRaises(AccessError):
            request.with_user(self.requester).write({'qty_pieces': 5})

    def test_a05_requester_cannot_edit_own_request_once_submitted(self):
        request = self._create_request()
        request.with_user(self.requester).action_submit()
        with self.assertRaises(AccessError):
            request.with_user(self.requester).write({'title': 'Cambio después de enviar'})

    def test_requester_cannot_set_operator_fields(self):
        request = self._create_request()
        with self.assertRaises(AccessError):
            request.with_user(self.requester).write({'planned_workcenter_id': self.printer1.id})
        with self.assertRaises(AccessError):
            self._create_request(requester_id=self.requester2.id)
        with self.assertRaises(AccessError):
            self._create_request(est_grams=50.0)

    def test_requester_cannot_run_operator_actions(self):
        request = self._create_request()
        request.with_user(self.requester).action_submit()
        for method in ('action_queue', 'action_request_info', 'action_reject', 'action_deliver'):
            with self.assertRaises(AccessError):
                getattr(request.with_user(self.requester), method)()
        with self.assertRaises(AccessError):
            request.with_user(self.requester2).action_cancel()

    def test_requester_read_only_on_jobs_and_catalogs(self):
        request = self._submit_and_queue(self._create_request())
        self._start(request, lots=self.lot_abs_1)
        self._finish(request, 'ok', [(self.lot_abs_1, 10.0)])
        job = request.job_ids.with_user(self.requester)
        self.assertTrue(job.name)
        self.assertTrue(job.workcenter_id.name)
        with self.assertRaises(AccessError):
            job.write({'pieces_ok': 5})
        with self.assertRaises(AccessError):
            self.env['imago.filament.material'].with_user(self.requester).create({'name': 'PEEK'})
        with self.assertRaises(AccessError):
            self.env['imago.print.purpose'].with_user(self.operator).create({'name': 'Otro'})
        self.env['imago.print.purpose'].with_user(self.manager).create({'name': 'Otro'})

    def test_operator_cannot_delete_manager_can(self):
        request = self._create_request()
        with self.assertRaises(AccessError):
            request.with_user(self.operator).unlink()
        with self.assertRaises(AccessError):
            request.with_user(self.requester).unlink()
        request.with_user(self.manager).unlink()
        self.assertFalse(request.exists())

    def test_groups_hierarchy(self):
        self.assertTrue(self.operator.has_group('mrp.group_mrp_user'))
        self.assertTrue(self.operator.has_group('stock.group_stock_user'))
        self.assertTrue(self.operator.has_group('imago_3dp.group_print_requester'))
        self.assertTrue(self.manager.has_group('imago_3dp.group_print_operator'))
        internal_user = self.env.ref('base.group_user')
        self.assertIn(self.env.ref('imago_3dp.group_print_requester'), internal_user.implied_ids)

    def test_requester_cannot_weigh_or_mount(self):
        with self.assertRaises(AccessError):
            self.env['imago.spool.weigh.wizard'].with_user(self.requester).create({
                'lot_id': self.lot_abs_1.id, 'gross_weight_g': 500.0})
        with self.assertRaises(AccessError):
            self.printer1.with_user(self.requester)._mount_lot(self.lot_abs_1)
        with self.assertRaises(AccessError):
            self.lot_abs_1.with_user(self.operator).with_user(self.requester).action_mark_empty()

    def test_multi_company_rule(self):
        other_company = self.env['res.company'].create({'name': 'Otra compañía'})
        request = self._create_request()
        request.sudo().company_id = other_company
        visible = self.env['imago.print.request'].with_user(self.requester2).search([('id', '=', request.id)])
        self.assertFalse(visible)

    def test_submit_requires_draft_or_needs_info(self):
        request = self._submit_and_queue(self._create_request())
        with self.assertRaises(UserError):
            request.with_user(self.operator).action_submit()

    # Review hardening ---------------------------------------------------
    def test_forged_context_cannot_change_state(self):
        request = self._create_request()
        as_requester = request.with_user(self.requester).with_context(imago_3dp_state_change=True)
        with self.assertRaises(UserError):
            as_requester.write({'state': 'queued'})
        with self.assertRaises(AccessError):
            as_requester.write({'planned_workcenter_id': self.printer1.id})
        with self.assertRaises(UserError):
            self.env['imago.print.request'].with_user(self.requester).with_context(
                imago_3dp_state_change=True).create({
                    'title': 'x', 'purpose_id': self.purpose.id, 'filament_product_id': self.filament_abs.id,
                    'qty_pieces': 1, 'date_required': '2026-12-01', 'state': 'needs_info'})
        self.assertEqual(request.state, 'draft')

    def test_requester_cannot_submit_other_request(self):
        request = self._create_request()
        with self.assertRaises(AccessError):
            request.with_user(self.requester2).action_submit()
        self.assertEqual(request.state, 'draft')
