# -*- coding: utf-8 -*-
from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, models

from .print_job import FAILURE_REASONS

FINISHED_RESULTS = ('ok', 'partial', 'failed')
CHART_DAYS = 30
OCCUPANCY_DAYS = 7
GRAMS_WEEKS = 8


class PrintDashboardCharts(models.AbstractModel):
    """Trend charts of the operator dashboard (SPEC 16.10, point 5)."""

    _inherit = 'imago.print.dashboard'

    def _charts(self, printers, now):
        return {
            'occupancy': self._chart_occupancy(printers, now),
            'failure_pareto': self._chart_failure_pareto(now),
            'success_by_printer': self._chart_success_by_printer(printers, now),
            'grams_by_purpose': self._chart_grams_by_purpose(now),
        }

    def _chart_occupancy(self, printers, now):
        """Machine hours per printer over the last days, from the standard
        productivity log (same source as the v0.1 occupancy report)."""
        since = now - timedelta(days=OCCUPANCY_DAYS)
        logs = self.env['mrp.workcenter.productivity'].search([
            ('workcenter_id', 'in', printers.ids),
            ('date_start', '<', now),
            '|', ('date_end', '=', False), ('date_end', '>', since),
        ])
        hours = defaultdict(float)
        for log in logs:
            start = max(log.date_start, since)
            end = min(log.date_end or now, now)
            if end > start:
                hours[log.workcenter_id.id] += (end - start).total_seconds() / 3600.0
        capacity = OCCUPANCY_DAYS * 24.0
        return [{
            'id': printer.id,
            'name': printer.name,
            'hours': round(hours[printer.id], 1),
            'pct': round(min(hours[printer.id] / capacity * 100.0, 100.0), 1),
        } for printer in printers]

    def _chart_failure_pareto(self, now):
        groups = self.env['imago.print.job'].read_group([
            ('result', 'in', ('partial', 'failed')),
            ('failure_reason', '!=', False),
            ('counts_for_printer', '=', True),
            ('date_end', '>=', now - timedelta(days=CHART_DAYS)),
        ], ['failure_reason'], ['failure_reason'])
        labels = dict(FAILURE_REASONS)
        rows = [{
            'reason': group['failure_reason'],
            'label': labels.get(group['failure_reason'], group['failure_reason']),
            'count': group['failure_reason_count'],
        } for group in groups]
        return sorted(rows, key=lambda row: (-row['count'], row['label']))

    def _chart_success_by_printer(self, printers, now):
        groups = self.env['imago.print.job'].read_group([
            ('workcenter_id', 'in', printers.ids),
            ('result', 'in', FINISHED_RESULTS),
            ('counts_for_printer', '=', True),
            ('date_end', '>=', now - timedelta(days=CHART_DAYS)),
        ], ['workcenter_id', 'result'], ['workcenter_id', 'result'], lazy=False)
        counts = defaultdict(int)
        for group in groups:
            counts[(group['workcenter_id'][0], group['result'])] = group['__count']
        return [dict(
            {'id': printer.id, 'name': printer.name},
            **{result: counts[(printer.id, result)] for result in FINISHED_RESULTS}
        ) for printer in printers]

    def _chart_grams_by_purpose(self, now):
        week_starts = self._week_starts(now)
        consumptions = self.env['imago.print.consumption'].search([
            ('stock_move_id', '!=', False),
            ('date', '>=', self._local_to_utc(week_starts[0])),
        ])
        series = defaultdict(lambda: [0.0] * len(week_starts))
        for consumption in consumptions:
            index = self._week_index(week_starts, self._utc_to_local(consumption.date).date())
            if index is not None:
                series[self._purpose_label(consumption)][index] += consumption.grams
        return {
            'weeks': [week.strftime('%d/%m') for week in week_starts],
            'series': [{'name': name, 'data': [round(value, 1) for value in values]}
                       for name, values in sorted(series.items())],
        }

    @api.model
    def _purpose_label(self, consumption):
        if consumption.source == 'production':
            return _('Producción')
        return consumption.purpose_id.name or _('Sin propósito')

    def _week_starts(self, now):
        today = self._utc_to_local(now).date()
        monday = today - timedelta(days=today.weekday())
        return [monday - timedelta(weeks=offset) for offset in range(GRAMS_WEEKS - 1, -1, -1)]

    @api.model
    def _week_index(self, week_starts, day):
        for index in range(len(week_starts) - 1, -1, -1):
            if day >= week_starts[index]:
                return index if day < week_starts[index] + timedelta(weeks=1) else None
        return None

    def _user_tz(self):
        return pytz.timezone(self.env.user.tz or 'UTC')

    def _utc_to_local(self, value):
        return pytz.utc.localize(value).astimezone(self._user_tz())

    def _local_to_utc(self, day):
        local = self._user_tz().localize(datetime.combine(day, time.min))
        return local.astimezone(pytz.utc).replace(tzinfo=None)
