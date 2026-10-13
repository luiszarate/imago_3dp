# -*- coding: utf-8 -*-
import base64

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import Form

from .common import Imago3dpCommon


@tagged('post_install', '-at_install')
class TestRequestFlow(Imago3dpCommon):

    # A-01 -------------------------------------------------------------
    def test_a01_requester_without_mrp_stock_creates_and_submits(self):
        self.assertFalse(self.requester.has_group('mrp.group_mrp_user'))
        self.assertFalse(self.requester.has_group('stock.group_stock_user'))
        self.assertTrue(self.requester.has_group('imago_3dp.group_print_requester'))
        model = self.env['imago.print.request'].with_user(self.requester)
        form = Form(model)
        form.title = 'Carcasa de GPS'
        form.purpose_id = self.purpose
        form.filament_product_id = self.filament_abs
        form.qty_pieces = 2
        form.date_required = fields.Date.today()
        form.file_url = 'https://cad.onshape.com/documents/123'
        request = form.save()
        self.assertEqual(request.state, 'draft')
        self.assertEqual(request.requester_id, self.requester)
        request.with_user(self.requester).action_submit()
        self.assertEqual(request.state, 'submitted')
        self.assertTrue(request.name.startswith('PRT-'))
        self.assertTrue(request.date_submitted)

    def test_a01_submit_with_attachment_only(self):
        attachment = self.env['ir.attachment'].with_user(self.requester).create({
            'name': 'pieza.stl',
            'datas': base64.b64encode(b'solid pieza\nendsolid pieza\n'),
        })
        request = self._create_request(file_url=False, file_ids=[(6, 0, attachment.ids)])
        request.with_user(self.requester).action_submit()
        self.assertEqual(request.state, 'submitted')

    # A-02 -------------------------------------------------------------
    def test_a02_submit_without_file_or_link_fails(self):
        request = self._create_request(file_url=False)
        with self.assertRaises(UserError):
            request.with_user(self.requester).action_submit()
        self.assertEqual(request.state, 'draft')

    # A-03 -------------------------------------------------------------
    def test_a03_submit_creates_activity_and_follower(self):
        request = self._create_request()
        request.with_user(self.requester).action_submit()
        review_type = self.env.ref('imago_3dp.mail_activity_review_request')
        activities = request.sudo().activity_ids.filtered(lambda a: a.activity_type_id == review_type)
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities.user_id, self.operator)
        self.assertEqual(request.operator_id, self.operator)
        self.assertIn(self.requester.partner_id, request.message_follower_ids.mapped('partner_id'))

    def test_a03_submit_without_default_operator_posts_to_operators(self):
        self.company.print3d_default_operator_id = False
        request = self._create_request()
        request.with_user(self.requester).action_submit()
        self.assertFalse(request.operator_id)
        message = request.message_ids.filtered(lambda m: self.operator.partner_id in m.partner_ids)
        self.assertTrue(message)

    # A-04 -------------------------------------------------------------
    def test_a04_request_info_and_resubmit(self):
        request = self._create_request()
        request.with_user(self.requester).action_submit()
        action = request.with_user(self.operator).action_request_info()
        wizard = Form(self.env[action['res_model']].with_user(self.operator).with_context(action['context']))
        wizard.message = '¿Qué espesor de pared necesitas?'
        wizard.save().action_confirm()
        self.assertEqual(request.state, 'needs_info')
        message = request.message_ids.filtered(lambda m: 'espesor de pared' in (m.body or ''))
        self.assertTrue(message)
        self.assertIn(self.requester.partner_id, message.partner_ids)
        review_type = self.env.ref('imago_3dp.mail_activity_review_request')
        self.assertFalse(request.sudo().activity_ids.filtered(lambda a: a.activity_type_id == review_type))
        # The requester edits and submits again
        request.with_user(self.requester).write({'notes': 'Pared de 2 mm', 'qty_pieces': 3})
        request.with_user(self.requester).action_submit()
        self.assertEqual(request.state, 'submitted')
        self.assertEqual(request.qty_pieces, 3)

    def test_reject_with_reason(self):
        request = self._create_request()
        request.with_user(self.requester).action_submit()
        action = request.with_user(self.operator).action_reject()
        wizard = Form(self.env[action['res_model']].with_user(self.operator).with_context(action['context']))
        wizard.message = 'Pieza fuera del volumen de impresión'
        wizard.save().action_confirm()
        self.assertEqual(request.state, 'rejected')
        self.assertEqual(request.reject_reason, 'Pieza fuera del volumen de impresión')

    # A-06 -------------------------------------------------------------
    def test_a06_start_creates_mo_once_and_mch_workorder(self):
        request = self._submit_and_queue(self._create_request(qty_pieces=2))
        job = self._start(request, lots=self.lot_abs_1, pieces=1)
        production = request.production_id
        self.assertTrue(production)
        self.assertEqual(production.print_request_id, request)
        self.assertIn(production.state, ('confirmed', 'progress'))
        workorder = job.workorder_id
        self.assertTrue(workorder.name.startswith('[MCH]'))
        self.assertEqual(workorder.workcenter_id, self.printer1)
        self.assertEqual(workorder.state, 'progress')
        self.assertEqual(self.printer1.printer_status, 'printing')
        self.assertEqual(self.printer1.current_request_id, request)
        self.assertEqual(self.printer1.mounted_lot_id, self.lot_abs_1)
        self.assertEqual(request.state, 'printing')
        # Second attempt: same MO, new WO
        self._finish(request, 'partial', [(self.lot_abs_1, 40.0)], pieces_ok=1, reason='adhesion')
        self.assertEqual(request.state, 'queued')
        self.assertEqual(self.printer1.printer_status, 'free')
        job2 = self._start(request, lots=self.lot_abs_1)
        self.assertEqual(request.production_id, production)
        self.assertEqual(job2.attempt_no, 2)
        self.assertEqual(job2.name, '%s/2' % request.name)
        self.assertEqual(len(production.workorder_ids.filtered(lambda w: w.name.startswith('[MCH]'))), 2)

    # A-07 -------------------------------------------------------------
    def test_a07_cannot_start_on_busy_or_out_of_service_printer(self):
        request_a = self._submit_and_queue(self._create_request())
        request_b = self._submit_and_queue(self._create_request(title='Otra pieza'))
        self._start(request_a, lots=self.lot_abs_1)
        with self.assertRaises(UserError):
            request_b.with_user(self.operator)._start_job(self.printer1, self.lot_abs_2, 1)
        # Out of service
        self.printer2.with_user(self.operator).action_toggle_out_of_service()
        self.assertEqual(self.printer2.printer_status, 'out_of_service')
        with self.assertRaises(UserError):
            request_b.with_user(self.operator)._start_job(self.printer2, self.lot_abs_2, 1)

    def test_a07_production_workorder_blocks_printer(self):
        holom_part = self.env['product.product'].create({'name': 'Wing LH ABS part', 'type': 'consu'})
        component = self.env['product.product'].create({'name': 'Inserto', 'type': 'consu'})
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': holom_part.product_tmpl_id.id,
            'product_qty': 1,
            'bom_line_ids': [(0, 0, {'product_id': component.id, 'product_qty': 1})],
            'operation_ids': [(0, 0, {'name': '70 [MCH] Imprimir componentes ABS',
                                      'workcenter_id': self.printer2.id, 'time_cycle_manual': 60})],
        })
        mo_form = Form(self.env['mrp.production'])
        mo_form.product_id = holom_part
        mo_form.bom_id = bom
        production = mo_form.save()
        production.action_confirm()
        production.workorder_ids.button_start()
        self.env['mrp.workcenter']._invalidate_printer_status()
        self.assertEqual(self.printer2.printer_status, 'printing')
        self.assertEqual(self.printer2.current_workorder_id, production.workorder_ids)
        self.assertFalse(self.printer2.current_request_id)
        request = self._submit_and_queue(self._create_request(), printer=self.printer2)
        with self.assertRaises(UserError):
            request.with_user(self.operator)._start_job(self.printer2, self.lot_abs_1, 1)

    # A-11 -------------------------------------------------------------
    def test_a11_complete_post_deliver_closes_mo_and_notifies(self):
        request = self._submit_and_queue(self._create_request(qty_pieces=2))
        self._start(request, lots=self.lot_abs_1)
        self._finish(request, 'ok', [(self.lot_abs_1, 120.0)])
        self.assertEqual(request.pieces_ok, 2)
        self.assertEqual(request.state, 'post')
        request.with_user(self.operator).action_deliver()
        self.assertEqual(request.state, 'done')
        self.assertTrue(request.date_done)
        production = request.production_id
        self.assertEqual(production.state, 'done')
        # filament consumed once (no double consumption when the MO is closed)
        self.assertAlmostEqual(self._lot_qty(self.lot_abs_1), 880.0)
        consumed = production.move_raw_ids.filtered(lambda m: m.state == 'done')
        self.assertAlmostEqual(sum(consumed.mapped('quantity_done')), 120.0)
        notice = request.message_ids.filtered(lambda m: 'lista para recoger' in (m.body or ''))
        self.assertTrue(notice)
        self.assertIn(self.requester.partner_id, notice.partner_ids)

    def test_post_reprint_then_deliver(self):
        request = self._submit_and_queue(self._create_request())
        self._start(request, lots=self.lot_abs_1)
        self._finish(request, 'ok', [(self.lot_abs_1, 50.0)])
        self.assertEqual(request.state, 'post')
        # defect found in post-processing: reprint from 'post'
        self._start(request, lots=self.lot_abs_1)
        self.assertEqual(request.state, 'printing')
        self._finish(request, 'ok', [(self.lot_abs_1, 50.0)])
        self.assertEqual(request.state, 'post')
        request.with_user(self.operator).action_deliver()
        self.assertEqual(request.production_id.state, 'done')

    # A-12 -------------------------------------------------------------
    def test_a12_labor_minutes_create_lab_workorder(self):
        request = self._submit_and_queue(self._create_request())
        job = self._start(request, lots=self.lot_abs_1)
        self._finish(request, 'ok', [(self.lot_abs_1, 60.0)], labor=30)
        labor_wo = job.labor_workorder_id
        self.assertTrue(labor_wo)
        self.assertTrue(labor_wo.name.startswith('[LAB]'))
        self.assertEqual(labor_wo.workcenter_id, self.labor_wc)
        self.assertEqual(labor_wo.state, 'done')
        self.assertEqual(labor_wo.time_ids.user_id, self.operator)
        self.assertAlmostEqual(sum(labor_wo.time_ids.mapped('duration')), 30.0, places=1)
        self.assertEqual(labor_wo.time_ids.loss_id.loss_type, 'productive')
        # [MCH] time stays on the printer and is separate from [LAB]
        mch_wo = job.workorder_id
        self.assertTrue(mch_wo.name.startswith('[MCH]'))
        self.assertEqual(mch_wo.state, 'done')
        self.assertEqual(mch_wo.time_ids.mapped('workcenter_id'), self.printer1)
        self.assertNotIn(self.labor_wc, mch_wo.time_ids.mapped('workcenter_id'))
        self.assertNotIn(self.printer1, labor_wo.time_ids.mapped('workcenter_id'))

    # Other transitions ------------------------------------------------
    def test_queue_requires_printer_and_warns_material(self):
        request = self._create_request()
        request.with_user(self.requester).action_submit()
        with self.assertRaises(UserError):
            request.with_user(self.operator).action_queue()
        request.with_user(self.operator).planned_workcenter_id = self.printer2  # PLA only
        request.with_user(self.operator).action_queue()
        self.assertEqual(request.state, 'queued')
        self.assertTrue(request.message_ids.filtered(lambda m: 'materiales compatibles' in (m.body or '')))

    def test_state_cannot_be_written_directly(self):
        request = self._create_request()
        with self.assertRaises(UserError):
            request.with_user(self.operator).write({'state': 'queued'})
        with self.assertRaises(UserError):
            request.with_user(self.requester).action_queue()  # not operator

    def test_kanban_group_expand(self):
        states = self.env['imago.print.request']._read_group_state([], [], None)
        self.assertEqual(states, ['submitted', 'needs_info', 'queued', 'printing', 'post'])

    def test_requester_cancels_submitted_request(self):
        request = self._create_request()
        request.with_user(self.requester).action_submit()
        request.with_user(self.requester).action_cancel()
        self.assertEqual(request.state, 'cancelled')
        review_type = self.env.ref('imago_3dp.mail_activity_review_request')
        self.assertFalse(request.sudo().activity_ids.filtered(lambda a: a.activity_type_id == review_type))

    def test_operator_cancels_while_printing(self):
        request = self._submit_and_queue(self._create_request())
        self._start(request, lots=self.lot_abs_1)
        action = request.with_user(self.operator).action_cancel()
        self.assertEqual(action['res_model'], 'imago.print.job.finish.wizard')
        self.assertTrue(action['context']['default_cancel_request'])
        job = self._finish(request, 'cancelled', [(self.lot_abs_1, 20.0)], cancel_request=True)
        self.assertEqual(job.result, 'cancelled')
        self.assertEqual(request.state, 'cancelled')
        # 20 g were consumed, so the MO is closed instead of cancelled
        self.assertEqual(request.production_id.state, 'done')
        self.assertAlmostEqual(self._lot_qty(self.lot_abs_1), 980.0)

    def test_operator_cancel_without_consumption_cancels_mo(self):
        request = self._submit_and_queue(self._create_request())
        self._start(request, lots=self.lot_abs_1)
        self._finish(request, 'cancelled', [(self.lot_abs_1, 0.0)])
        self.assertEqual(request.state, 'queued')
        request.with_user(self.operator).action_cancel()
        self.assertEqual(request.state, 'cancelled')
        self.assertEqual(request.production_id.state, 'cancel')

    def test_reopen_by_manager(self):
        request = self._submit_and_queue(self._create_request())
        self._start(request, lots=self.lot_abs_1)
        self._finish(request, 'ok', [(self.lot_abs_1, 30.0)])
        request.with_user(self.operator).action_deliver()
        old_production = request.production_id
        with self.assertRaises(Exception):
            request.with_user(self.operator).action_reopen()
        request.with_user(self.manager).action_reopen()
        self.assertEqual(request.state, 'queued')
        self.assertFalse(request.production_id)
        self._start(request, lots=self.lot_abs_1)
        self.assertNotEqual(request.production_id, old_production)
        self.assertEqual(request.production_count, 2)

    def test_no_substitute_restricts_spools(self):
        request = self._submit_and_queue(self._create_request(allow_substitute=False))
        with self.assertRaises(UserError):
            request.with_user(self.operator)._start_job(self.printer1, self.lot_pla_1, 1)
        wizard = self.env['imago.print.job.start.wizard'].with_user(self.operator).with_context(
            default_request_id=request.id).create({})
        self.assertNotIn(self.lot_pla_1, wizard.allowed_lot_ids)
        self.assertIn(self.lot_abs_1, wizard.allowed_lot_ids)

    def test_start_wizard_defaults_and_warning(self):
        self.printer1.sudo().mounted_lot_id = self.lot_abs_2
        request = self._submit_and_queue(self._create_request(qty_pieces=4), est_grams=5000.0)
        wizard = Form(self.env['imago.print.job.start.wizard'].with_user(self.operator).with_context(
            default_request_id=request.id))
        self.assertEqual(wizard.workcenter_id, self.printer1)
        self.assertEqual(wizard.pieces_planned, 4)
        self.assertEqual(wizard.est_grams, 5000.0)
        self.assertEqual(wizard.lot_ids[:], self.lot_abs_2)
        self.assertIn('g', wizard.warning_text or '')

    # Review hardening ---------------------------------------------------
    def test_reject_from_queue_closes_mo(self):
        request = self._submit_and_queue(self._create_request())
        self._start(request, lots=self.lot_abs_1)
        self._finish(request, 'failed', [(self.lot_abs_1, 20.0)], reason='clog')
        self.assertEqual(request.state, 'queued')
        request.with_user(self.operator)._do_reject('Se rediseña la pieza')
        self.assertEqual(request.state, 'rejected')
        self.assertEqual(request.production_id.state, 'done')

    def test_reject_from_queue_without_consumption_cancels_mo(self):
        request = self._submit_and_queue(self._create_request())
        self._start(request, lots=self.lot_abs_1)
        self._finish(request, 'cancelled', [(self.lot_abs_1, 0.0)])
        request.with_user(self.operator)._do_reject('Ya no se necesita')
        self.assertEqual(request.production_id.state, 'cancel')

    def test_reopen_keeps_old_consumption_on_old_mo(self):
        request = self._submit_and_queue(self._create_request())
        self._start(request, lots=self.lot_abs_1)
        job1 = self._finish(request, 'ok', [(self.lot_abs_1, 30.0)])
        request.with_user(self.operator).action_deliver()
        old_production = request.production_id
        request.with_user(self.manager).action_reopen()
        self._start(request, lots=self.lot_abs_1)
        self.assertNotEqual(request.production_id, old_production)
        job1.consumption_ids.invalidate_cache()
        self.assertEqual(job1.consumption_ids.production_id, old_production)

    def test_reopen_unsubmitted_request_goes_to_draft(self):
        request = self._create_request()
        request.with_user(self.requester).action_cancel()
        request.with_user(self.manager).action_reopen()
        self.assertEqual(request.state, 'draft')

    def test_start_mounts_printer_current_spool_when_selected(self):
        self.printer1.sudo().mounted_lot_id = self.lot_abs_2
        request = self._submit_and_queue(self._create_request())
        self._start(request, lots=self.lot_abs_1 | self.lot_abs_2)
        self.assertEqual(self.printer1.mounted_lot_id, self.lot_abs_2)
