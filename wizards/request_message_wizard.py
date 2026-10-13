# -*- coding: utf-8 -*-
from odoo import fields, models


class RequestMessageWizard(models.TransientModel):
    _name = 'imago.print.request.message.wizard'
    _description = 'Mensaje al solicitante (aclaración / rechazo)'

    request_id = fields.Many2one('imago.print.request', string='Solicitud', required=True, ondelete='cascade')
    mode = fields.Selection(
        [('info', 'Pedir aclaración'), ('reject', 'Rechazar')], string='Acción', required=True, default='info')
    message = fields.Text(string='Mensaje', required=True)

    def action_confirm(self):
        self.ensure_one()
        if self.mode == 'reject':
            self.request_id._do_reject(self.message)
        else:
            self.request_id._do_request_info(self.message)
        return {'type': 'ir.actions.act_window_close'}
