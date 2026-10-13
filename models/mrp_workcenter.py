# -*- coding: utf-8 -*-
from datetime import timedelta

import psycopg2

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

PRINTER_STATUS = [
    ('free', 'Libre'),
    ('printing', 'Imprimiendo'),
    ('out_of_service', 'Fuera de servicio'),
]


class MrpWorkcenter(models.Model):
    _inherit = 'mrp.workcenter'

    is_3d_printer = fields.Boolean(string='Es impresora 3D')
    printer_model = fields.Char(string='Modelo de impresora')
    allowed_material_ids = fields.Many2many(
        'imago.filament.material', string='Materiales compatibles',
        help='Vacío = acepta todos los materiales.')
    mounted_lot_id = fields.Many2one(
        'stock.production.lot', string='Carrete montado',
        domain="[('is_spool', '=', True)]", copy=False)
    mounted_lot_remaining_pct = fields.Float(
        related='mounted_lot_id.spool_remaining_pct', string='% restante del carrete')
    mounted_lot_remaining_g = fields.Float(
        related='mounted_lot_id.spool_remaining_g', string='Gramos restantes del carrete')
    out_of_service = fields.Boolean(string='Fuera de servicio', copy=False)
    printer_status = fields.Selection(
        PRINTER_STATUS, string='Estado de la impresora', compute='_compute_printer_status')
    current_workorder_id = fields.Many2one(
        'mrp.workorder', string='WO en curso', compute='_compute_printer_status')
    current_request_id = fields.Many2one(
        'imago.print.request', string='Solicitud en curso', compute='_compute_printer_status')
    current_eta = fields.Datetime(string='Fin estimado', compute='_compute_printer_status')

    @api.depends('out_of_service')
    def _compute_printer_status(self):
        real_ids = [wc_id for wc_id in self.ids if isinstance(wc_id, int)]
        workorders = self.env['mrp.workorder'].sudo().search(
            [('workcenter_id', 'in', real_ids), ('state', '=', 'progress')], order='date_start desc')
        jobs = self.env['imago.print.job'].sudo().search(
            [('workorder_id', 'in', workorders.ids), ('result', '=', 'running')])
        job_by_wo = {job.workorder_id.id: job for job in jobs}
        for workcenter in self:
            workorder = workorders.filtered(lambda wo: wo.workcenter_id.id == workcenter.id)[:1]
            job = job_by_wo.get(workorder.id)
            workcenter.current_workorder_id = workorder.id
            workcenter.current_request_id = job.request_id.id if job else False
            workcenter.current_eta = workcenter._printer_eta(workorder, job)
            if workcenter.out_of_service:
                workcenter.printer_status = 'out_of_service'
            elif workorder:
                workcenter.printer_status = 'printing'
            else:
                workcenter.printer_status = 'free'

    @api.model
    def _invalidate_printer_status(self):
        self.invalidate_cache(fnames=['printer_status', 'current_workorder_id', 'current_request_id', 'current_eta'])

    def _lock_printer(self):
        """Row lock so two operators cannot start on the same printer concurrently."""
        self.ensure_one()
        try:
            with self.env.cr.savepoint(flush=False):
                self.env.cr.execute('SELECT id FROM mrp_workcenter WHERE id = %s FOR UPDATE NOWAIT', (self.id,))
        except psycopg2.OperationalError:
            raise UserError(_('Otro usuario está iniciando una impresión en %s; intenta de nuevo.')
                            % self.display_name)

    def _printer_running_workorder(self):
        """Work order in progress on this printer, read from the database (the
        non-stored ``printer_status`` may be cached within the transaction)."""
        self.ensure_one()
        return self.env['mrp.workorder'].sudo().search(
            [('workcenter_id', '=', self.id), ('state', '=', 'progress')], limit=1)

    @api.model
    def _printer_eta(self, workorder, job):
        if not workorder or not workorder.date_start:
            return False
        minutes = (job.est_minutes if job else 0) or workorder.duration_expected
        return workorder.date_start + timedelta(minutes=minutes or 0)

    def _check_print_operator(self):
        if not self.env.user.has_group('imago_3dp.group_print_operator'):
            raise AccessError(_('Solo el operador de impresión 3D puede realizar esta acción.'))

    def _mount_lot(self, lot):
        """Mount ``lot`` on this printer and unmount it from any other printer.

        mrp.group_mrp_user cannot write work centers, so this narrow write runs as
        superuser after checking the 3D operator group.
        """
        self.ensure_one()
        self._check_print_operator()
        if lot and not lot.is_spool:
            raise UserError(_('El lote %s no es un carrete de filamento.') % lot.name)
        if lot:
            others = self.sudo().search([('mounted_lot_id', '=', lot.id), ('id', '!=', self.id)])
            others.write({'mounted_lot_id': False})
        self.sudo().write({'mounted_lot_id': lot.id if lot else False})

    def action_open_mount_wizard(self):
        self.ensure_one()
        return {
            'name': _('Montar carrete'),
            'type': 'ir.actions.act_window',
            'res_model': 'imago.spool.mount.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_workcenter_id': self.id, 'default_lot_id': self.mounted_lot_id.id},
        }

    def action_toggle_out_of_service(self):
        self._check_print_operator()
        for workcenter in self:
            workcenter.sudo().write({'out_of_service': not workcenter.out_of_service})
        return True
