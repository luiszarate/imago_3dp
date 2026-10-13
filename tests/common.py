# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.tests.common import Form, SavepointCase, new_test_user


class Imago3dpCommon(SavepointCase):
    """Printers, filament, spools and one user per security group."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.company = env.company
        cls.warehouse = env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.location_3dp = env['stock.location'].create({
            'name': '3DP',
            'location_id': cls.warehouse.lot_stock_id.id,
            'usage': 'internal',
        })
        cls.gram = env.ref('uom.product_uom_gram')
        cls.kg = env.ref('uom.product_uom_kgm')
        cls.mat_abs = env.ref('imago_3dp.material_abs')
        cls.mat_pla = env.ref('imago_3dp.material_pla')
        cls.purpose = env.ref('imago_3dp.purpose_holom_prototype')
        cls.purpose_tooling = env.ref('imago_3dp.purpose_holom_tooling')

        Workcenter = env['mrp.workcenter']
        cls.labor_wc = Workcenter.create({'name': '3DP', 'code': '3DP'})
        cls.printer1 = Workcenter.create({
            'name': '3DP-01', 'code': '3DP-01', 'is_3d_printer': True, 'printer_model': 'Prusa MK4'})
        cls.printer2 = Workcenter.create({
            'name': '3DP-02', 'code': '3DP-02', 'is_3d_printer': True, 'printer_model': 'Prusa MK4',
            'allowed_material_ids': [(6, 0, cls.mat_pla.ids)]})

        cls.requester = new_test_user(
            env, login='ing_requester', name='Ingeniera Solicitante', email='ing1@example.com',
            groups='base.group_user')
        cls.requester2 = new_test_user(
            env, login='ing_requester2', name='Ingeniero Dos', email='ing2@example.com',
            groups='base.group_user')
        cls.operator = new_test_user(
            env, login='print_operator', name='Operador 3D', email='op3d@example.com',
            groups='base.group_user,imago_3dp.group_print_operator')
        cls.manager = new_test_user(
            env, login='print_manager', name='Responsable 3D', email='mgr3d@example.com',
            groups='base.group_user,imago_3dp.group_print_manager')

        cls.company.write({
            'print3d_location_id': cls.location_3dp.id,
            'print3d_default_operator_id': cls.operator.id,
            'print3d_labor_workcenter_id': cls.labor_wc.id,
            'print3d_low_spool_g': 150.0,
        })

        cls.filament_abs = cls._create_filament('ABS Negro 1.75', cls.mat_abs, 'Negro', tare=250.0)
        cls.filament_pla = cls._create_filament('PLA Blanco 1.75', cls.mat_pla, 'Blanco', tare=200.0)
        cls.lot_abs_1 = cls._create_spool(cls.filament_abs, 1000.0)
        cls.lot_abs_2 = cls._create_spool(cls.filament_abs, 1000.0)
        cls.lot_pla_1 = cls._create_spool(cls.filament_pla, 1000.0)

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------
    @classmethod
    def _create_filament(cls, name, material, color, tare=0.0):
        return cls.env['product.product'].create({
            'name': name,
            'type': 'product',
            'tracking': 'lot',
            'uom_id': cls.gram.id,
            'uom_po_id': cls.kg.id,
            'is_filament': True,
            'filament_material_id': material.id,
            'filament_color': color,
            'spool_nominal_g': 1000.0,
            'spool_tare_g': tare,
        })

    @classmethod
    def _create_spool(cls, product, grams):
        Lot = cls.env['stock.production.lot']
        lot = Lot.create({
            'name': Lot._spool_generate_name(product),
            'product_id': product.id,
            'company_id': cls.company.id,
        })
        if grams:
            cls.env['stock.quant']._update_available_quantity(product, cls.location_3dp, grams, lot_id=lot)
        return lot

    def _create_request(self, user=None, **values):
        vals = {
            'title': 'Soporte de antena v3',
            'purpose_id': self.purpose.id,
            'filament_product_id': self.filament_abs.id,
            'qty_pieces': 1,
            'date_required': fields.Date.today() + timedelta(days=7),
            'file_url': 'https://drive.example.com/soporte.stl',
        }
        vals.update(values)
        request = self.env['imago.print.request'].with_user(user or self.requester).create(vals)
        # Return it in the test (superuser) environment; tests act as a given user explicitly.
        return request.with_env(self.env)

    def _submit_and_queue(self, request, printer=None, est_grams=80.0, est_minutes=120):
        request.with_user(request.requester_id).action_submit()
        as_operator = request.with_user(self.operator)
        as_operator.write({
            'planned_workcenter_id': (printer or self.printer1).id,
            'est_grams': est_grams,
            'est_print_minutes': est_minutes,
        })
        as_operator.action_queue()
        return request

    def _start(self, request, printer=None, lots=None, pieces=None):
        wizard_model = self.env['imago.print.job.start.wizard'].with_user(self.operator).with_context(
            default_request_id=request.id)
        form = Form(wizard_model)
        if printer:
            form.workcenter_id = printer
        if lots is not None:
            form.lot_ids.clear()
            for lot in lots:
                form.lot_ids.add(lot)
        if pieces is not None:
            form.pieces_planned = pieces
        form.save().action_start()
        return request.job_ids.filtered(lambda j: j.result == 'running')

    def _finish(self, request, result, lines, pieces_ok=None, reason=False, note=False, labor=0,
                cancel_request=False):
        """``lines``: list of (lot, grams); lots not pre-filled are added as new lines."""
        job = request.job_ids.filtered(lambda j: j.result == 'running')
        ctx = {'default_job_id': job.id}
        if cancel_request:
            ctx.update(default_result='cancelled', default_cancel_request=True)
        form = Form(self.env['imago.print.job.finish.wizard'].with_user(self.operator).with_context(**ctx))
        form.result = result
        grams_by_lot = dict((lot, grams) for lot, grams in lines)
        for index in range(len(form.line_ids)):
            with form.line_ids.edit(index) as line:
                line.grams = grams_by_lot.pop(line.lot_id, 0.0)
        for lot, grams in grams_by_lot.items():
            with form.line_ids.new() as line:
                line.lot_id = lot
                line.grams = grams
        if pieces_ok is not None:
            form.pieces_ok = pieces_ok
        if reason:
            form.failure_reason = reason
        if note:
            form.failure_note = note
        if labor:
            form.labor_minutes = labor
        form.save().action_finish()
        return job

    def _lot_qty(self, lot):
        lot.invalidate_cache()
        return sum(lot.quant_ids.filtered(
            lambda q: q.location_id.parent_path.startswith(self.location_3dp.parent_path)).mapped('quantity'))
