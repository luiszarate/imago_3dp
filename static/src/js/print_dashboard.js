odoo.define('imago_3dp.PrintDashboard', function (require) {
"use strict";

var AbstractAction = require('web.AbstractAction');
var core = require('web.core');
var charts = require('imago_3dp.PrintDashboardCharts');

var QWeb = core.qweb;
var _t = core._t;

var REFRESH_MS = 15000;
var CHART_EVERY_N_REFRESH = 4;
var WALL_STORAGE_KEY = 'imago_3dp.dashboard.wall';
// Wall mode shows the next action at poster scale plus the three after it.
var WALL_VISIBLE_ACTIONS = 4;
// Rows the one-screen wall layout lists before counting the rest as "+N más".
var WALL_LIMITS = {queue: 7, filaments: 5, critical: 4};
var SEVERITY = {
    critical: {label: _t('Urgente'), icon: 'fa-exclamation-circle'},
    warning: {label: _t('Atención'), icon: 'fa-exclamation-triangle'},
    info: {label: _t('Aviso'), icon: 'fa-info-circle'},
};
var STATUS_ICON = {free: 'fa-check', printing: 'fa-cog', out_of_service: 'fa-ban'};
var QUEUE_GROUPS = [
    ['submitted', _t('Por revisar')],
    ['queued', _t('En cola')],
    ['post', _t('Post-proceso')],
];
var TREND_CAPTIONS = {
    occupancy: _t('Horas de máquina [MCH] registradas por impresora en los últimos 7 días.'),
    success: _t('Intentos terminados por impresora en los últimos 30 días.'),
    failure: _t('Causa registrada en intentos fallidos o parciales de los últimos 30 días.'),
    grams: _t('Gramos descontados de carretes por semana, según el propósito de la solicitud.'),
};

/**
 * Flags the rows past ``limit`` so wall mode can hide them and say how many.
 * @returns {{rows: Object[], more: number}}
 */
function limitForWall(rows, limit) {
    return {
        rows: _.map(rows, function (row, index) {
            return _.extend({}, row, {wall_extra: index >= limit});
        }),
        more: Math.max(0, rows.length - limit),
    };
}

function readWallPreference() {
    try {
        return window.localStorage.getItem(WALL_STORAGE_KEY) === '1';
    } catch (error) {
        return false;
    }
}

function writeWallPreference(enabled) {
    try {
        window.localStorage.setItem(WALL_STORAGE_KEY, enabled ? '1' : '0');
    } catch (error) {
        // Private windows may block storage; the mode still works for this visit.
    }
}

var PrintDashboard = AbstractAction.extend({
    contentTemplate: 'imago_3dp.Dashboard',
    jsLibs: ['/imago_3dp/static/lib/echarts/echarts.min.js'],
    events: {
        'click .o_p3d_open': '_onOpenRecord',
        'click .o_p3d_call': '_onCallMethod',
        'click .o_p3d_refresh': '_onRefreshClick',
        'click .o_p3d_trend_tabs .nav-link': '_onTrendTab',
        'click .o_p3d_wall_toggle': '_onWallToggle',
    },

    init: function () {
        this._super.apply(this, arguments);
        this.data = null;
        this.chart = null;
        this.trend = 'occupancy';
        this.refreshCount = 0;
        this.seenActions = null;
        this.wall = readWallPreference();
        this._onVisibilityChange = this._onVisibilityChange.bind(this);
        this._onFullscreenChange = this._onFullscreenChange.bind(this);
        this._onResize = _.debounce(this._resizeChart.bind(this), 150);
    },
    willStart: function () {
        var self = this;
        return Promise.all([this._super.apply(this, arguments), this._fetch(true).then(function (data) {
            self.data = data;
        })]);
    },
    on_attach_callback: function () {
        this._super.apply(this, arguments);
        this._applyWall(this.wall);
        this._initChart();
        this._render();
        if (this.wasAttached) {
            // Coming back from a form or wizard: the data on screen may be stale.
            this.refreshCount = CHART_EVERY_N_REFRESH - 1;
            this._refresh();
        }
        this.wasAttached = true;
        this._startTimer();
        document.addEventListener('visibilitychange', this._onVisibilityChange);
        document.addEventListener('fullscreenchange', this._onFullscreenChange);
        window.addEventListener('resize', this._onResize);
    },
    on_detach_callback: function () {
        this._unbind();
        this._clearWallChrome();
        this._super.apply(this, arguments);
    },
    destroy: function () {
        this._unbind();
        this._clearWallChrome();
        if (this.chart) {
            this.chart.dispose();
            this.chart = null;
        }
        this._super.apply(this, arguments);
    },
    _clearWallChrome: function () {
        // Wall mode styles the whole page; never leak it to other Odoo screens.
        $('body').removeClass('o_p3d_wall_mode');
        document.documentElement.classList.remove('o_p3d_wall_root');
    },
    _unbind: function () {
        this._stopTimer();
        document.removeEventListener('visibilitychange', this._onVisibilityChange);
        document.removeEventListener('fullscreenchange', this._onFullscreenChange);
        window.removeEventListener('resize', this._onResize);
    },

    //--------------------------------------------------------------------------
    // Data
    //--------------------------------------------------------------------------

    _fetch: function (includeCharts) {
        return this._rpc({
            model: 'imago.print.dashboard',
            method: 'get_dashboard_data',
            kwargs: {include_charts: includeCharts},
        });
    },
    _refresh: function () {
        var self = this;
        this.refreshCount += 1;
        var includeCharts = this.refreshCount % CHART_EVERY_N_REFRESH === 0;
        return this._fetch(includeCharts).then(function (data) {
            if (!includeCharts && self.data) {
                data.charts = self.data.charts;
            }
            self.data = data;
            self.error = false;
            self._render();
        }).guardedCatch(function () {
            // Keep the last data on screen; the RPC layer already reports the error.
            self.error = true;
            self._renderStatus();
        });
    },
    _startTimer: function () {
        var self = this;
        this._stopTimer();
        this.timer = setInterval(function () {
            if (document.visibilityState === 'visible') {
                self._refresh();
            }
        }, REFRESH_MS);
    },
    _stopTimer: function () {
        if (this.timer) {
            clearInterval(this.timer);
            this.timer = null;
        }
    },

    //--------------------------------------------------------------------------
    // Rendering
    //--------------------------------------------------------------------------

    _render: function () {
        var view = this._viewModel(this.data);
        this.$('.o_p3d_summary_counts').html(QWeb.render('imago_3dp.DashboardSummary', {view: view}));
        this.$('.o_p3d_actions_count').text(view.actions.length ? '(' + view.actions.length + ')' : '');
        this.$('.o_p3d_wall_next_slot').html(QWeb.render('imago_3dp.DashboardWallNext', {view: view}));
        this.$('.o_p3d_actions_body').html(QWeb.render('imago_3dp.DashboardActions', {view: view}));
        this.$('.o_p3d_stations').html(QWeb.render('imago_3dp.DashboardStations', {view: view}));
        this.$('.o_p3d_queue').html(QWeb.render('imago_3dp.DashboardQueue', {view: view}));
        this.$('.o_p3d_spools').html(QWeb.render('imago_3dp.DashboardSpools', {view: view}));
        this._renderStatus();
        this._renderChart();
    },
    _renderStatus: function () {
        var text = this.error ?
            _t('Sin conexión con Odoo; se muestran los últimos datos') :
            _.str.sprintf(_t('Actualizado %s'), moment().format('HH:mm:ss'));
        this.$('.o_p3d_status').text(text).toggleClass('o_p3d_text_critical', !!this.error);
    },
    _viewModel: function (data) {
        var queue = _.map(data.queue, function (row) {
            return _.extend({}, row, {
                date_label: row.date_required ? moment(row.date_required).format('DD/MM') : '',
            });
        });
        return {
            kpis: data.kpis,
            actions: this._actionsView(data.actions),
            wall_hidden_actions: Math.max(0, data.actions.length - WALL_VISIBLE_ACTIONS),
            printers: _.map(data.printers, this._printerView.bind(this, queue)),
            queue: this._queueView(queue),
            spools: this._spoolsView(data.spools),
        };
    },
    _queueView: function (queue) {
        var ordered = _.flatten(_.map(QUEUE_GROUPS, function (group) {
            return _.where(queue, {state: group[0]});
        }), true);
        var limited = limitForWall(ordered, WALL_LIMITS.queue);
        var groups = _.compact(_.map(QUEUE_GROUPS, function (group) {
            var rows = _.where(limited.rows, {state: group[0]});
            return rows.length ? {
                state: group[0], label: group[1], rows: rows,
                wall_extra: _.every(rows, 'wall_extra'),
            } : null;
        }));
        return {groups: groups, wall_more: limited.more};
    },
    _spoolsView: function (spools) {
        var summary = limitForWall(_.map(spools.summary, function (row) {
            return _.extend({}, row, {grams_label: row.grams.toLocaleString('es-MX')});
        }), WALL_LIMITS.filaments);
        var critical = limitForWall(_.map(spools.critical, function (lot) {
            return _.extend({}, lot, {grams_label: Math.round(lot.remaining_g).toLocaleString('es-MX')});
        }), WALL_LIMITS.critical);
        return {
            summary: summary.rows,
            critical: critical.rows,
            wall_more: summary.more + critical.more,
        };
    },
    _actionsView: function (actions) {
        var seen = this.seenActions;
        this.seenActions = _.object(_.pluck(actions, 'key'), _.map(actions, _.constant(true)));
        return _.map(actions, function (action) {
            return _.extend({}, action, {
                severity_label: SEVERITY[action.severity].label,
                icon: SEVERITY[action.severity].icon,
                is_new: !!seen && !seen[action.key],
            });
        });
    },
    _printerView: function (queue, card) {
        var view = _.extend({}, card, {
            status_icon: STATUS_ICON[card.status] || 'fa-circle-o',
            eta_label: card.eta ? this._formatTime(card.eta) : '',
            next_in_queue: card.status === 'free' && _.findWhere(queue, {state: 'queued', printer_id: card.id}),
        });
        if (card.job) {
            view.job_g = Math.round(card.job.est_grams);
            view.progress_label = Math.round(card.job.progress_est);
        }
        if (card.spool) {
            view.spool_g = Math.round(card.spool.remaining_g).toLocaleString('es-MX');
            view.spool_pct = Math.max(0, Math.min(100, Math.round(card.spool.remaining_pct)));
            view.spool_warn = card.filament_warning || _.contains(['low', 'empty'], card.spool.state);
        }
        return view;
    },
    _formatTime: function (utcString) {
        var value = moment.utc(utcString).local();
        return value.isSame(moment(), 'day') ? value.format('HH:mm') : value.format('DD/MM HH:mm');
    },

    //--------------------------------------------------------------------------
    // Trends (Apache ECharts)
    //--------------------------------------------------------------------------

    _initChart: function () {
        var node = this.el.querySelector('.o_p3d_chart');
        if (!window.echarts || this.chart || !node) {
            return;
        }
        this.chart = window.echarts.init(node, null, {renderer: 'svg'});
    },
    _resizeChart: function () {
        if (this.chart) {
            this.chart.resize();
        }
    },
    _renderChart: function () {
        var data = this.data && this.data.charts;
        var trend = this.trend;
        this.$('.o_p3d_trend_tabs .nav-link').each(function (index, link) {
            link.classList.toggle('active', link.dataset.trend === trend);
            link.setAttribute('aria-selected', link.dataset.trend === trend ? 'true' : 'false');
        });
        this.$('.o_p3d_trend_caption').text(TREND_CAPTIONS[this.trend]);
        if (!data || !this.chart) {
            return;
        }
        var built = charts.build(this.trend, data);
        this.$('.o_p3d_chart_box').toggleClass('o_p3d_chart_empty', !built.hasData);
        this.$('.o_p3d_chart').attr('aria-label', built.summary);
        this.chart.setOption(built.option, true);
    },

    //--------------------------------------------------------------------------
    // Wall mode
    //--------------------------------------------------------------------------

    _applyWall: function (enabled) {
        this.wall = enabled;
        this.$('.o_print3d_dashboard').toggleClass('o_p3d_wall', enabled);
        $('body').toggleClass('o_p3d_wall_mode', enabled);
        document.documentElement.classList.toggle('o_p3d_wall_root', enabled);
        this.$('.o_p3d_wall_toggle_label').text(enabled ? _t('Salir de modo pantalla') : _t('Modo pantalla'));
        this.$('.o_p3d_wall_toggle').attr('aria-pressed', enabled ? 'true' : 'false');
        _.defer(this._resizeChart.bind(this));
    },

    //--------------------------------------------------------------------------
    // Handlers
    //--------------------------------------------------------------------------

    _onOpenRecord: function (ev) {
        ev.preventDefault();
        if (this.wall) {
            return;
        }
        var target = ev.currentTarget.dataset;
        this.do_action({
            type: 'ir.actions.act_window',
            res_model: target.model,
            res_id: parseInt(target.id, 10),
            views: [[false, 'form']],
            target: 'current',
        });
    },
    _onCallMethod: function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var self = this;
        var button = ev.currentTarget;
        var target = button.dataset;
        button.disabled = true;
        // Same route as form buttons: the server completes the returned action (views, context).
        this._rpc({
            route: '/web/dataset/call_button',
            params: {
                model: target.model,
                method: target.method,
                args: [[parseInt(target.id, 10)]],
                kwargs: {context: this.getSession().user_context},
            },
        }).then(function (action) {
            if (action && typeof action === 'object') {
                return self.do_action(action, {on_close: self._refresh.bind(self)});
            }
            return self._refresh();
        }).finally(function () {
            button.disabled = false;
        });
    },
    _onRefreshClick: function (ev) {
        ev.preventDefault();
        this.refreshCount = CHART_EVERY_N_REFRESH - 1;
        this._refresh();
    },
    _onTrendTab: function (ev) {
        ev.preventDefault();
        this.trend = ev.currentTarget.dataset.trend;
        this._renderChart();
    },
    _onWallToggle: function (ev) {
        ev.preventDefault();
        var enabled = !this.wall;
        writeWallPreference(enabled);
        this._applyWall(enabled);
        var root = document.documentElement;
        if (enabled && root.requestFullscreen && !document.fullscreenElement) {
            root.requestFullscreen().catch(function () {
                // The browser may refuse full screen; the enlarged layout still applies.
            });
        } else if (!enabled && document.fullscreenElement && document.exitFullscreen) {
            document.exitFullscreen();
        }
    },
    _onFullscreenChange: function () {
        _.defer(this._resizeChart.bind(this));
    },
    _onVisibilityChange: function () {
        if (document.visibilityState === 'visible') {
            this._refresh();
        }
    },
});

core.action_registry.add('imago_3dp_dashboard', PrintDashboard);

return PrintDashboard;

});
