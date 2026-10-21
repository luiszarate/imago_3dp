# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import html_escape, plaintext2html

REQUEST_STATES = [
    ('draft', 'Borrador'),
    ('submitted', 'Enviada'),
    ('needs_info', 'Aclarar'),
    ('queued', 'En cola'),
    ('printing', 'Imprimiendo'),
    ('post', 'Post-proceso'),
    ('done', 'Entregada'),
    ('rejected', 'Rechazada'),
    ('cancelled', 'Cancelada'),
]
FINAL_STATES = ('done', 'rejected', 'cancelled')
EDITABLE_STATES = ('draft', 'needs_info')
REQUESTER_CANCEL_STATES = ('draft', 'submitted', 'needs_info')
KANBAN_STATES = ('submitted', 'needs_info', 'queued', 'printing', 'post')


# Fields only the 3D operator may set (requesters fill the "Solicitud" group).
OPERATOR_FIELDS = (
    'operator_id', 'planned_workcenter_id', 'est_print_minutes', 'est_grams',
    'production_id', 'reject_reason', 'date_submitted', 'date_done', 'name', 'requester_id',
)

OPERATOR_GROUP = 'imago_3dp.group_print_operator'
MANAGER_GROUP = 'imago_3dp.group_print_manager'
REVIEW_ACTIVITY = 'imago_3dp.mail_activity_review_request'


class PrintRequest(models.Model):
    _name = 'imago.print.request'
    _description = 'Solicitud de impresión 3D'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'priority desc, date_required asc, id desc'

    name = fields.Char(string='Folio', readonly=True, copy=False, default=lambda self: _('Nuevo'))
    title = fields.Char(string='¿Qué se imprime?', required=True, tracking=True)
    requester_id = fields.Many2one(
        'res.users', string='Solicitante', required=True, tracking=True,
        default=lambda self: self.env.user)
    purpose_id = fields.Many2one('imago.print.purpose', string='Propósito', required=True)
    reference = fields.Char(string='Referencia', help='SN de Holom, código de proyecto, part number…')
    filament_product_id = fields.Many2one(
        'product.product', string='Filamento', required=True,
        domain="[('is_filament', '=', True)]")
    filament_material_id = fields.Many2one(
        related='filament_product_id.filament_material_id', string='Material')
    filament_color = fields.Char(related='filament_product_id.filament_color', string='Color')
    allow_substitute = fields.Boolean(string='Acepto material/color equivalente', default=True)
    qty_pieces = fields.Integer(string='Piezas', required=True, default=1)
    date_required = fields.Date(string='Fecha requerida', required=True, tracking=True)
    priority = fields.Selection(
        [('0', 'Normal'), ('1', 'Alta'), ('2', 'Urgente')], string='Prioridad', default='0')
    file_ids = fields.Many2many(
        'ir.attachment', 'imago_print_request_attachment_rel', 'request_id', 'attachment_id',
        string='Archivos', help='STL, 3MF, STEP…')
    file_url = fields.Char(string='Link al archivo', help='Drive, Onshape, etc.')
    infill_pct = fields.Integer(string='Relleno (%)')
    layer_height_mm = fields.Float(string='Altura de capa (mm)', digits=(4, 2))
    supports = fields.Selection(
        [('auto', 'Decide el operador'), ('yes', 'Sí'), ('no', 'No')], string='Soportes', default='auto')
    notes = fields.Text(string='Notas técnicas')
    state = fields.Selection(
        REQUEST_STATES, string='Estado', default='draft', required=True, tracking=True,
        copy=False, group_expand='_read_group_state')
    operator_id = fields.Many2one(
        'res.users', string='Operador', tracking=True,
        domain=lambda self: [('groups_id', 'in', self.env.ref(OPERATOR_GROUP).id)])
    planned_workcenter_id = fields.Many2one(
        'mrp.workcenter', string='Impresora prevista', domain="[('is_3d_printer', '=', True)]")
    est_print_minutes = fields.Integer(string='Minutos estimados (slicer)')
    est_grams = fields.Float(string='Gramos estimados (slicer)')
    production_id = fields.Many2one('mrp.production', string='Orden de fabricación', readonly=True, copy=False)
    production_ids = fields.One2many('mrp.production', 'print_request_id', string='Órdenes de fabricación')
    production_count = fields.Integer(compute='_compute_production_count')
    job_ids = fields.One2many('imago.print.job', 'request_id', string='Intentos', copy=False)
    job_count = fields.Integer(string='Nº de intentos', compute='_compute_job_stats')
    pieces_ok = fields.Integer(string='Piezas OK', compute='_compute_job_stats')
    pieces_pending = fields.Integer(string='Piezas pendientes', compute='_compute_job_stats')
    grams_total = fields.Float(string='Gramos consumidos', compute='_compute_totals', store=True)
    grams_failed = fields.Float(string='Gramos en intentos fallidos', compute='_compute_totals', store=True)
    print_minutes_total = fields.Float(string='Minutos de impresión', compute='_compute_totals', store=True)
    is_late = fields.Boolean(string='Atrasada', compute='_compute_is_late', search='_search_is_late')
    reject_reason = fields.Text(string='Motivo de rechazo', readonly=True, copy=False)
    date_submitted = fields.Datetime(string='Fecha de envío', readonly=True, copy=False)
    date_done = fields.Datetime(string='Fecha de entrega', readonly=True, copy=False)
    company_id = fields.Many2one(
        'res.company', string='Compañía', required=True, default=lambda self: self.env.company)
    user_is_operator = fields.Boolean(
        string='El usuario es operador', compute='_compute_user_is_operator',
        help='Técnico: controla qué campos puede editar el usuario en el formulario.')

    _sql_constraints = [
        ('qty_pieces_positive', 'CHECK(qty_pieces > 0)', 'La cantidad de piezas debe ser mayor a cero.'),
    ]

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.model
    def _read_group_state(self, states, domain, order):
        return [key for key, _label in REQUEST_STATES if key in KANBAN_STATES or key in states]

    @api.depends('job_ids.pieces_ok', 'qty_pieces')
    def _compute_job_stats(self):
        for request in self:
            request.job_count = len(request.job_ids)
            request.pieces_ok = sum(request.job_ids.mapped('pieces_ok'))
            request.pieces_pending = max(request.qty_pieces - request.pieces_ok, 0)

    @api.depends('job_ids.grams_total', 'job_ids.result', 'job_ids.allocated_minutes')
    def _compute_totals(self):
        for request in self:
            jobs = request.job_ids
            request.grams_total = sum(jobs.mapped('grams_total'))
            request.grams_failed = sum(jobs.filtered(lambda j: j.result == 'failed').mapped('grams_total'))
            # A combined print counts only this request's share of the plate time (SPEC 17, D-23).
            request.print_minutes_total = sum(jobs.mapped('allocated_minutes'))

    def _compute_user_is_operator(self):
        is_operator = self._is_print_operator()
        for request in self:
            request.user_is_operator = is_operator

    def _compute_production_count(self):
        for request in self:
            request.production_count = len(request.sudo().production_ids)

    @api.depends('date_required', 'state')
    def _compute_is_late(self):
        today = fields.Date.context_today(self)
        for request in self:
            request.is_late = bool(
                request.date_required and request.date_required < today and request.state not in FINAL_STATES)

    def _search_is_late(self, operator, value):
        today = fields.Date.context_today(self)
        late_domain = [('date_required', '<', today), ('state', 'not in', FINAL_STATES)]
        positive = (operator == '=' and value) or (operator == '!=' and not value)
        if positive:
            return late_domain
        return ['|', '|', ('date_required', '=', False), ('date_required', '>=', today),
                ('state', 'in', FINAL_STATES)]

    # ------------------------------------------------------------------
    # ORM guards
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('state') and vals['state'] != 'draft' and not self.env.su:
                raise UserError(_('Las solicitudes se crean en borrador.'))
            self._check_operator_fields(vals)
        return super().create(vals_list)

    def write(self, vals):
        # State changes only come from the action_* methods through _set_state (sudo):
        # env.su cannot be forged from an RPC context, unlike a context flag.
        if 'state' in vals and not self.env.su:
            raise UserError(_('El estado de la solicitud solo cambia con los botones del formulario.'))
        self._check_operator_fields(vals)
        return super().write(vals)

    @api.model
    def _check_operator_fields(self, vals):
        if self.env.su or self._is_print_operator():
            return
        protected = [key for key in OPERATOR_FIELDS if vals.get(key)]
        if vals.get('requester_id') == self.env.uid:
            protected.remove('requester_id')
        if protected:
            labels = ', '.join(self._fields[key].string for key in protected)
            raise AccessError(_('Solo el operador de impresión 3D puede modificar: %s') % labels)

    def unlink(self):
        if self.mapped('job_ids.consumption_ids').filtered('stock_move_id'):
            raise UserError(_('No se puede borrar una solicitud con consumo de filamento registrado; '
                              'cancélala en su lugar.'))
        return super().unlink()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    def _is_print_operator(self):
        return self.env.user.has_group(OPERATOR_GROUP)

    def _check_operator(self):
        if not self.env.su and not self._is_print_operator():
            raise AccessError(_('Solo el operador de impresión 3D puede realizar esta acción.'))

    def _check_state(self, allowed, action_label):
        state_labels = dict(REQUEST_STATES)
        for request in self:
            if request.state not in allowed:
                raise UserError(_(
                    'No se puede %(action)s la solicitud %(name)s en estado "%(state)s".',
                    action=action_label, name=request.name, state=state_labels[request.state]))

    def _set_state(self, vals):
        """Write a state transition. Callers must have validated state, group and
        ownership first; sudo keeps env.user, so tracking/chatter author is the user."""
        return self.sudo().write(vals)

    def _notify_requester(self, body):
        for request in self:
            request.message_post(
                body=body, partner_ids=request.requester_id.partner_id.ids,
                message_type='comment', subtype_xmlid='mail.mt_comment')

    def _close_review_activity(self):
        self.sudo().activity_feedback([REVIEW_ACTIVITY])

    def _warn_material_compatibility(self, workcenter):
        """Non-blocking warning when the printer does not list the requested material."""
        self.ensure_one()
        material = self.filament_product_id.filament_material_id
        allowed = workcenter.allowed_material_ids
        if not allowed or material in allowed:
            return False
        warning = _('Advertencia: la impresora %(printer)s no tiene el material %(material)s entre sus '
                    'materiales compatibles.', printer=html_escape(workcenter.display_name),
                    material=html_escape(material.display_name))
        self.message_post(body=warning)
        return warning

    # ------------------------------------------------------------------
    # Requester actions
    # ------------------------------------------------------------------
    def action_submit(self):
        self._check_state(EDITABLE_STATES, _('enviar'))
        for request in self:
            if not self.env.su:
                # _set_state runs as sudo: enforce the requester record rule explicitly.
                request.check_access_rights('write')
                request.check_access_rule('write')
            if not request.file_ids and not (request.file_url or '').strip():
                raise UserError(_('Adjunta el archivo (STL/3MF/STEP) o indica el link antes de enviar.'))
            vals = {'state': 'submitted', 'date_submitted': fields.Datetime.now()}
            if not request.name or request.name == _('Nuevo'):
                vals['name'] = self.env['ir.sequence'].sudo().with_company(request.company_id).next_by_code(
                    'imago.print.request') or _('Nuevo')
            operator = request.operator_id or request.company_id.print3d_default_operator_id
            if operator and not request.operator_id:
                vals['operator_id'] = operator.id
            request._set_state(vals)
            request._notify_submitted()
        return True

    def _notify_submitted(self):
        """Follower + review activity. Runs as superuser because the requester loses
        write access once the request leaves the draft/needs_info states."""
        self.ensure_one()
        request = self.sudo()
        request.message_subscribe(partner_ids=self.requester_id.partner_id.ids)
        if self.operator_id:
            request.activity_schedule(
                REVIEW_ACTIVITY,
                summary=_('Revisar solicitud de impresión'),
                note=html_escape('%s – %s' % (self.name, self.title)),
                user_id=self.operator_id.id)
            return
        operators = self.env.ref(OPERATOR_GROUP).sudo().users.filtered(
            lambda u: self.company_id in u.company_ids)
        request.message_post(
            body=_('Nueva solicitud de impresión %s enviada. No hay operador por defecto configurado.') % self.name,
            partner_ids=operators.mapped('partner_id').ids,
            message_type='comment', subtype_xmlid='mail.mt_comment')

    def action_cancel(self):
        is_operator = self._is_print_operator()
        for request in self:
            if request.state in FINAL_STATES:
                raise UserError(_('La solicitud %s ya está cerrada.') % request.name)
            if not is_operator and not self.env.su:
                if request.requester_id != self.env.user or request.state not in REQUESTER_CANCEL_STATES:
                    raise AccessError(_('Solo puedes cancelar tus solicitudes en borrador, enviadas o en aclaración.'))
                request.sudo()._do_cancel()
                continue
            running = request.job_ids.filtered(lambda j: j.result == 'running')
            if running.batch_id:
                raise UserError(_('La solicitud %(name)s está en la impresión combinada %(batch)s: termínala '
                                  'antes de cancelar.', name=request.name, batch=running.batch_id.name))
            if running:
                if len(self) > 1:
                    raise UserError(_('La solicitud %s tiene un intento en curso: cancélala individualmente.')
                                    % request.name)
                return running[0]._action_open_finish_wizard(cancel_request=True)
            request._do_cancel()
        return True

    def _do_cancel(self):
        for request in self:
            request._cancel_production()
            request._set_state({'state': 'cancelled'})
            request.sudo().activity_unlink([REVIEW_ACTIVITY])
        return True

    # ------------------------------------------------------------------
    # Operator actions
    # ------------------------------------------------------------------
    def _open_message_wizard(self, mode):
        self.ensure_one()
        return {
            'name': _('Pedir aclaración') if mode == 'info' else _('Rechazar solicitud'),
            'type': 'ir.actions.act_window',
            'res_model': 'imago.print.request.message.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id, 'default_mode': mode},
        }

    def action_request_info(self):
        self._check_operator()
        self._check_state(('submitted', 'queued'), _('pedir aclaración de'))
        return self._open_message_wizard('info')

    def action_reject(self):
        self._check_operator()
        self._check_state(('submitted', 'queued'), _('rechazar'))
        return self._open_message_wizard('reject')

    def _do_request_info(self, message):
        self._check_operator()
        self._check_state(('submitted', 'queued'), _('pedir aclaración de'))
        if not (message or '').strip():
            raise UserError(_('Escribe qué información necesitas.'))
        for request in self:
            request._set_state({'state': 'needs_info'})
            request._notify_requester(plaintext2html(message))
            request._close_review_activity()
        return True

    def _do_reject(self, reason):
        self._check_operator()
        self._check_state(('submitted', 'queued'), _('rechazar'))
        if not (reason or '').strip():
            raise UserError(_('Indica el motivo del rechazo.'))
        for request in self:
            request._cancel_production()
            request._set_state({'state': 'rejected', 'reject_reason': reason})
            request._notify_requester(
                plaintext2html(_('Tu solicitud %s fue rechazada:\n%s') % (request.name, reason)))
            request._close_review_activity()
        return True

    def action_queue(self):
        self._check_operator()
        self._check_state(('submitted',), _('poner en cola'))
        for request in self:
            if not request.planned_workcenter_id:
                raise UserError(_('Selecciona la impresora prevista antes de poner en cola.'))
            request._set_state({'state': 'queued'})
            request._warn_material_compatibility(request.planned_workcenter_id)
            request._close_review_activity()
        return True

    def action_open_start_wizard(self):
        self.ensure_one()
        self._check_operator()
        self._check_state(('queued', 'post'), _('iniciar un intento de'))
        return {
            'name': _('Iniciar impresión'),
            'type': 'ir.actions.act_window',
            'res_model': 'imago.print.job.start.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def action_open_finish_wizard(self):
        self.ensure_one()
        self._check_operator()
        running = self.job_ids.filtered(lambda j: j.result == 'running')
        if not running:
            raise UserError(_('No hay un intento en curso para la solicitud %s.') % self.name)
        if running[0].batch_id:
            return running[0].batch_id._action_open_finish_wizard()
        return running[0]._action_open_finish_wizard()

    def action_deliver(self):
        self._check_operator()
        self._check_state(('post',), _('entregar'))
        for request in self:
            if request.job_ids.filtered(lambda j: j.result == 'running'):
                raise UserError(_('Termina el intento en curso antes de entregar.'))
            request._close_production()
            request._set_state({'state': 'done', 'date_done': fields.Datetime.now()})
            request._notify_requester(_('Tu impresión %s está lista para recoger.') % request.name)
        return True

    def action_reopen(self):
        if not self.env.su and not self.env.user.has_group(MANAGER_GROUP):
            raise AccessError(_('Solo el responsable de impresión 3D puede reabrir solicitudes.'))
        self._check_state(FINAL_STATES, _('reabrir'))
        for request in self:
            submitted = bool(request.date_submitted)
            vals = {'state': 'queued' if submitted else 'draft', 'date_done': False}
            if request.production_id.state in ('done', 'cancel'):
                vals['production_id'] = False
            request._set_state(vals)
            request.message_post(body=_('Solicitud reabierta y puesta en cola.') if submitted
                                 else _('Solicitud reabierta como borrador.'))
        return True

    # ------------------------------------------------------------------
    # Attempts / MRP integration
    # ------------------------------------------------------------------
    def _start_job(self, workcenter, lots, pieces_planned, est_grams=0.0, est_minutes=0):
        """Start a new print attempt: MO (first time), [MCH] WO started, job + consumption lines."""
        self.ensure_one()
        self._check_operator()
        self._check_state(('queued', 'post'), _('iniciar un intento de'))
        self._check_start_conditions(workcenter, lots, pieces_planned)
        production = self._ensure_production()
        attempt_no = self._next_attempt_no()
        workorder = self._create_machine_workorder(
            production, workcenter, _('[MCH] Impresión 3D – %s – intento %s') % (self.name, attempt_no),
            est_minutes)
        job = self._create_job(workcenter, lots, pieces_planned, attempt_no, workorder,
                               est_grams=est_grams, est_minutes=est_minutes)
        self._after_job_started(job, workcenter, lots)
        return job

    def _next_attempt_no(self):
        self.ensure_one()
        return max(self.job_ids.mapped('attempt_no') or [0]) + 1

    @api.model
    def _create_machine_workorder(self, production, workcenter, name, est_minutes):
        """[MCH] work order on ``production``, started (its timer is the printer occupancy)."""
        workorder = self.env['mrp.workorder'].create({
            'name': name,
            'production_id': production.id,
            'workcenter_id': workcenter.id,
            'product_uom_id': production.product_uom_id.id,
            'consumption': 'flexible',
            'duration_expected': est_minutes or 60.0,
            'state': 'ready',
        })
        workorder.button_start()
        return workorder

    def _create_job(self, workcenter, lots, pieces_planned, attempt_no, workorder, est_grams=0.0, est_minutes=0,
                    batch=False, share=1.0):
        """Running attempt with a 0 g consumption line per spool (grams are captured at the end).
        Attempts of a combined print other than the lead one have no work order (SPEC 17, D-22)."""
        self.ensure_one()
        job = self.env['imago.print.job'].create({
            'request_id': self.id,
            'attempt_no': attempt_no,
            'workcenter_id': workcenter.id,
            'workorder_id': workorder.id,
            'operator_id': self.env.user.id,
            'pieces_planned': pieces_planned,
            'est_grams': est_grams,
            'est_minutes': est_minutes,
            'date_start': fields.Datetime.now(),
            'result': 'running',
            'consumption_ids': [
                (0, 0, {'lot_id': lot.id, 'grams': 0.0, 'workorder_id': workorder.id}) for lot in lots
            ],
        })
        if batch:
            # Batch fields are protected against direct writes (RPC); the batch already checked the operator.
            job.sudo().write({'batch_id': batch.id, 'share': share})
        return job

    def _after_job_started(self, job, workcenter, lots, batch=False):
        self.ensure_one()
        mounted = workcenter.mounted_lot_id if workcenter.mounted_lot_id in lots else lots[0]
        workcenter._mount_lot(mounted)
        workcenter._invalidate_printer_status()
        self._set_state({'state': 'printing'})
        self._warn_material_compatibility(workcenter)
        if batch:
            others = batch.request_ids - self
            self.message_post(body=_(
                'Intento %(attempt)s iniciado en %(printer)s dentro de la impresión combinada %(batch)s '
                'con %(others)s.', attempt=job.name, printer=html_escape(workcenter.display_name),
                batch=html_escape(batch.name), others=html_escape(', '.join(others.mapped('name')))))
            return
        self.message_post(body=_(
            'Intento %(attempt)s iniciado en %(printer)s con carrete(s) %(lots)s.',
            attempt=job.name, printer=html_escape(workcenter.display_name),
            lots=html_escape(', '.join(lots.mapped('name')))))

    def _check_start_conditions(self, workcenter, lots, pieces_planned):
        if not workcenter or not workcenter.is_3d_printer:
            raise UserError(_('Selecciona una impresora 3D.'))
        if workcenter.out_of_service:
            raise UserError(_('La impresora %s está fuera de servicio.') % workcenter.display_name)
        workcenter._lock_printer()
        running = workcenter._printer_running_workorder()
        if running:
            raise UserError(_('La impresora %(printer)s está ocupada con %(wo)s.',
                              printer=workcenter.display_name, wo=running.display_name))
        if not lots:
            raise UserError(_('Selecciona al menos un carrete.'))
        not_spools = lots.filtered(lambda lot: not lot.is_spool)
        if not_spools:
            raise UserError(_('Estos lotes no son carretes de filamento: %s') % ', '.join(not_spools.mapped('name')))
        if not self.allow_substitute:
            wrong = lots.filtered(lambda lot: lot.product_id != self.filament_product_id)
            if wrong:
                raise UserError(_('La solicitud no acepta sustitutos; los carretes %(lots)s no son de %(product)s.',
                                  lots=', '.join(wrong.mapped('name')),
                                  product=self.filament_product_id.display_name))
        if pieces_planned <= 0:
            raise UserError(_('Las piezas planeadas deben ser mayores a cero.'))

    def _ensure_production(self):
        """Create and confirm the generic MO of the request (first attempt).

        Odoo 14 refuses to confirm an MO without component moves (also with an empty
        BOM), so a 0 g placeholder raw move of the requested filament is added; it is
        cancelled automatically when the MO is marked as done (see SPEC §14).
        """
        self.ensure_one()
        if self.production_id and self.production_id.state not in ('done', 'cancel'):
            return self.production_id
        company = self.company_id
        product = company._print3d_get_product()
        location = company._print3d_get_location()
        origin = ' | '.join(part for part in (self.name, self.purpose_id.name, self.reference) if part)
        production = self.env['mrp.production'].with_company(company).create({
            'product_id': product.id,
            'product_qty': 1,
            'product_uom_id': product.uom_id.id,
            'bom_id': False,
            'origin': origin,
            'location_src_id': location.id,
            'company_id': company.id,
            'print_request_id': self.id,
        })
        Move = self.env['stock.move']
        Move.create(production._get_moves_finished_values())
        placeholder = production._get_move_raw_values(
            self.filament_product_id, 0.0, self.filament_product_id.uom_id)
        placeholder['name'] = _('%s (marcador de filamento)') % production.name
        Move.create(placeholder)
        production.action_confirm()
        self.production_id = production
        return production

    def _after_job_finished(self, job, cancelling=False):
        self.ensure_one()
        if cancelling:
            return
        new_state = 'post' if self.pieces_ok >= self.qty_pieces else 'queued'
        self._set_state({'state': new_state})
        result_label = dict(job._fields['result'].selection)[job.result]
        self.message_post(body=_(
            'Intento %(job)s terminado: %(result)s, piezas OK %(ok)s/%(qty)s, %(grams).1f g.',
            job=job.name, result=result_label, ok=self.pieces_ok, qty=self.qty_pieces, grams=job.grams_total))

    def _close_production(self):
        """Mark the request MO as done (consumption already posted per attempt)."""
        self.ensure_one()
        production = self.production_id
        if not production or production.state in ('done', 'cancel'):
            return True
        production.workorder_ids.filtered(lambda wo: wo.state not in ('done', 'cancel')).button_finish()
        production.qty_producing = production.product_qty
        production.with_context(skip_backorder=True, skip_consumption=True).button_mark_done()
        if production.state != 'done':
            raise UserError(_('No se pudo cerrar la orden de fabricación %s; ciérrala manualmente.')
                            % production.name)
        return True

    def _cancel_production(self):
        self.ensure_one()
        production = self.production_id
        if not production or production.state in ('done', 'cancel'):
            return True
        if any(move.state == 'done' for move in production.move_raw_ids):
            return self._close_production()
        return production.action_cancel()

    # ------------------------------------------------------------------
    # Smart buttons
    # ------------------------------------------------------------------
    def action_view_jobs(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('imago_3dp.action_print_job')
        action['domain'] = [('request_id', '=', self.id)]
        action['context'] = {'default_request_id': self.id}
        return action

    def action_view_production(self):
        self.ensure_one()
        self._check_operator()
        productions = self.production_ids
        action = {
            'name': _('Órdenes de fabricación'),
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
        }
        if len(productions) == 1:
            action.update({'view_mode': 'form', 'res_id': productions.id})
        else:
            action.update({'view_mode': 'tree,form', 'domain': [('id', 'in', productions.ids)]})
        return action
