# -*- coding: utf-8 -*-
import re

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import Form

from .common import Imago3dpCommon


@tagged('post_install', '-at_install')
class TestSpools(Imago3dpCommon):

    # A-14 -------------------------------------------------------------
    def test_a14_generate_spools_on_receipt(self):
        supplier = self.env['res.partner'].create({'name': 'Filamentos SA'})
        picking_type = self.warehouse.in_type_id
        picking = self.env['stock.picking'].create({
            'partner_id': supplier.id,
            'picking_type_id': picking_type.id,
            'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': self.warehouse.lot_stock_id.id,
            'move_lines': [(0, 0, {
                'name': self.filament_abs.name,
                'product_id': self.filament_abs.id,
                'product_uom': self.kg.id,
                'product_uom_qty': 3.0,
                'location_id': self.env.ref('stock.stock_location_suppliers').id,
                'location_dest_id': self.warehouse.lot_stock_id.id,
            })],
        })
        picking.action_confirm()
        self.assertTrue(picking.has_filament_moves)
        action = picking.with_user(self.operator).action_open_spool_receive_wizard()
        form = Form(self.env[action['res_model']].with_user(self.operator).with_context(action['context']))
        self.assertEqual(len(form.line_ids), 1)
        with form.line_ids.edit(0) as line:
            self.assertAlmostEqual(line.qty_g, 3000.0)
            self.assertEqual(line.spool_count, 3)
            self.assertAlmostEqual(line.grams_per_spool, 1000.0)
        form.save().action_generate()
        picking.with_user(self.operator).button_validate()
        self.assertEqual(picking.state, 'done')
        lots = picking.move_line_ids.mapped('lot_id')
        self.assertEqual(len(lots), 3)
        for lot in lots:
            self.assertTrue(re.match(r'^ABS-NEG-\d{4}$', lot.name), lot.name)
            self.assertAlmostEqual(self._lot_qty(lot), 1000.0)
            self.assertAlmostEqual(lot.spool_remaining_g, 1000.0)
            self.assertEqual(lot.spool_state, 'new')
            self.assertTrue(lot.is_spool)
        self.assertEqual(set(picking.move_line_ids.mapped('location_dest_id').ids), {self.location_3dp.id})
        # Running the wizard twice on the same move is refused
        picking2 = picking.copy()
        picking2.action_confirm()
        picking2.move_lines.move_line_ids = [(0, 0, {
            'product_id': self.filament_abs.id, 'product_uom_id': self.gram.id, 'qty_done': 1.0,
            'lot_id': lots[0].id, 'location_id': picking2.location_id.id,
            'location_dest_id': self.location_3dp.id, 'picking_id': picking2.id})]
        wizard = self.env['imago.spool.receive.wizard'].with_user(self.operator).with_context(
            default_picking_id=picking2.id).create({})
        with self.assertRaises(UserError):
            wizard.action_generate()

    # A-15 -------------------------------------------------------------
    def test_a15_weigh_spool(self):
        form = Form(self.env['imago.spool.weigh.wizard'].with_user(self.operator).with_context(
            default_lot_id=self.lot_abs_1.id))
        self.assertAlmostEqual(form.tare_g, 250.0)
        form.gross_weight_g = 570.0
        self.assertAlmostEqual(form.net_g, 320.0)
        self.assertAlmostEqual(form.diff_g, -680.0)
        form.save().action_confirm()
        self.assertAlmostEqual(self._lot_qty(self.lot_abs_1), 320.0)
        self.assertAlmostEqual(self.lot_abs_1.spool_remaining_g, 320.0)
        message = self.lot_abs_1.message_ids.filtered(lambda m: '-680.0' in (m.body or ''))
        self.assertTrue(message)
        inventory = self.env['stock.inventory'].search([('name', 'ilike', self.lot_abs_1.name)])
        self.assertEqual(inventory.state, 'done')

    def test_weigh_negative_net_refused(self):
        wizard = self.env['imago.spool.weigh.wizard'].with_user(self.operator).create({
            'lot_id': self.lot_abs_1.id, 'gross_weight_g': 100.0, 'tare_g': 250.0})
        with self.assertRaises(UserError):
            wizard.action_confirm()

    def test_weigh_spool_without_stock(self):
        lot = self._create_spool(self.filament_abs, 0.0)
        self.assertEqual(lot.spool_state, 'empty')
        wizard = self.env['imago.spool.weigh.wizard'].with_user(self.operator).create({
            'lot_id': lot.id, 'gross_weight_g': 1250.0, 'tare_g': 250.0})
        wizard.action_confirm()
        self.assertAlmostEqual(self._lot_qty(lot), 1000.0)
        self.assertEqual(lot.spool_state, 'new')

    # A-16 -------------------------------------------------------------
    def test_a16_low_spool_warns_operator(self):
        lot = self._create_spool(self.filament_abs, 200.0)
        self.assertEqual(lot.spool_state, 'new')
        request = self._submit_and_queue(self._create_request())
        self._start(request, lots=lot)
        self._finish(request, 'ok', [(lot, 60.0)])
        self.assertAlmostEqual(lot.spool_remaining_g, 140.0)
        self.assertEqual(lot.spool_state, 'low')
        low_type = self.env.ref('imago_3dp.mail_activity_low_spool')
        activity = lot.activity_ids.filtered(lambda a: a.activity_type_id == low_type)
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity.user_id, self.operator)
        self.assertTrue(request.message_ids.filtered(lambda m: 'casi vacío' in (m.body or '')))
        # A second consumption does not duplicate the activity
        self._start(request, lots=lot)
        self._finish(request, 'ok', [(lot, 10.0)])
        self.assertEqual(len(lot.activity_ids.filtered(lambda a: a.activity_type_id == low_type)), 1)

    def test_threshold_change_recomputes_state(self):
        lot = self._create_spool(self.filament_abs, 300.0)
        self.assertEqual(lot.spool_state, 'new')
        self.company.print3d_low_spool_g = 400.0
        self.assertEqual(lot.spool_state, 'low')

    # Mark empty / mount ------------------------------------------------
    def test_mark_empty_unmounts(self):
        self.printer1.with_user(self.operator)._mount_lot(self.lot_abs_1)
        self.assertEqual(self.lot_abs_1.mounted_workcenter_id, self.printer1)
        self.lot_abs_1.with_user(self.operator).action_mark_empty()
        self.assertAlmostEqual(self._lot_qty(self.lot_abs_1), 0.0)
        self.assertEqual(self.lot_abs_1.spool_state, 'empty')
        self.assertFalse(self.printer1.mounted_lot_id)

    def test_mount_wizard_moves_spool_between_printers(self):
        self.printer1.with_user(self.operator)._mount_lot(self.lot_pla_1)
        wizard = self.env['imago.spool.mount.wizard'].with_user(self.operator).create({
            'workcenter_id': self.printer2.id, 'lot_id': self.lot_pla_1.id})
        wizard.action_confirm()
        self.assertEqual(self.printer2.mounted_lot_id, self.lot_pla_1)
        self.assertFalse(self.printer1.mounted_lot_id)
        self.assertEqual(self.lot_pla_1.mounted_workcenter_id, self.printer2)

    # Naming / product setup -------------------------------------------
    def test_spool_name_slug(self):
        product = self._create_filament('PETG Azul Índigo', self.env.ref('imago_3dp.material_petg'), 'Índigo')
        name = self.env['stock.production.lot']._spool_generate_name(product)
        self.assertTrue(re.match(r'^PETG-IND-\d{4}$', name), name)

    def test_filament_product_constraints(self):
        with self.assertRaises(ValidationError):
            self.env['product.product'].create({
                'name': 'Filamento mal configurado', 'type': 'consu', 'is_filament': True,
                'filament_material_id': self.mat_abs.id, 'filament_color': 'Rojo'})
        with self.assertRaises(ValidationError):
            self.env['product.product'].create({
                'name': 'Filamento sin lote', 'type': 'product', 'tracking': 'none', 'is_filament': True,
                'filament_material_id': self.mat_abs.id, 'filament_color': 'Rojo',
                'uom_id': self.gram.id, 'uom_po_id': self.kg.id})
        with self.assertRaises(ValidationError):
            self.env['product.product'].create({
                'name': 'Filamento en piezas', 'type': 'product', 'tracking': 'lot', 'is_filament': True,
                'filament_material_id': self.mat_abs.id, 'filament_color': 'Rojo'})

    def test_filament_onchange_proposes_setup(self):
        form = Form(self.env['product.template'])
        form.name = 'ASA Gris'
        form.is_filament = True
        self.assertEqual(form.type, 'product')
        self.assertEqual(form.tracking, 'lot')
        self.assertEqual(form.uom_id, self.gram)
        self.assertEqual(form.uom_po_id, self.kg)

    def test_filament_must_use_grams(self):
        with self.assertRaises(ValidationError):
            self.env['product.product'].create({
                'name': 'Filamento en kg', 'type': 'product', 'tracking': 'lot', 'is_filament': True,
                'filament_material_id': self.mat_abs.id, 'filament_color': 'Rojo',
                'uom_id': self.kg.id, 'uom_po_id': self.kg.id})

    def test_cannot_adjust_non_spool_lot(self):
        other = self.env['product.product'].create({'name': 'Tornillo', 'type': 'product', 'tracking': 'lot'})
        lot = self.env['stock.production.lot'].create({
            'name': 'TOR-1', 'product_id': other.id, 'company_id': self.company.id})
        self.env['stock.quant']._update_available_quantity(other, self.location_3dp, 10, lot_id=lot)
        wizard = self.env['imago.spool.weigh.wizard'].with_user(self.operator).create({
            'lot_id': lot.id, 'gross_weight_g': 500.0, 'tare_g': 0.0})
        with self.assertRaises(UserError):
            wizard.action_confirm()
