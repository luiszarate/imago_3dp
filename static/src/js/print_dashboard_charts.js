odoo.define('imago_3dp.PrintDashboardCharts', function (require) {
"use strict";

/**
 * ECharts options for the dashboard trend tabs. Pure functions of the data
 * returned by ``imago.print.dashboard.get_dashboard_data``.
 */
var core = require('web.core');

var _t = core._t;

var FONT = 'Roboto, "Helvetica Neue", Arial, sans-serif';
// Reference data-viz palette: categorical slots in fixed order; status colors reserved.
var SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'];
var STATUS = {ok: '#0ca30c', partial: '#fab219', failed: '#d03b3b'};
var INK = {primary: '#4c4c4c', secondary: '#5f5e5a', muted: '#6c757d', grid: '#ebeae6', surface: '#ffffff'};

function base() {
    return {
        textStyle: {fontFamily: FONT, color: INK.secondary, fontSize: 12},
        grid: {left: 4, right: 40, top: 12, bottom: 4, containLabel: true},
        tooltip: {
            trigger: 'axis',
            axisPointer: {type: 'shadow', shadowStyle: {color: 'rgba(124, 123, 173, 0.08)'}},
            backgroundColor: INK.surface,
            borderColor: INK.grid,
            textStyle: {color: INK.primary, fontFamily: FONT, fontSize: 12},
            extraCssText: 'box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);',
        },
        animationDuration: 300,
        animationEasing: 'cubicOut',
    };
}

function valueAxis(extra) {
    return _.extend({
        type: 'value',
        axisLabel: {color: INK.muted},
        splitLine: {lineStyle: {color: INK.grid}},
    }, extra || {});
}

function categoryAxis(labels, extra) {
    return _.extend({
        type: 'category',
        data: labels,
        axisLine: {lineStyle: {color: INK.grid}},
        axisTick: {show: false},
        axisLabel: {color: INK.secondary, width: 140, overflow: 'truncate'},
    }, extra || {});
}

function legend() {
    return {top: 0, left: 0, itemWidth: 10, itemHeight: 10, icon: 'roundRect', textStyle: {color: INK.secondary}};
}

function occupancy(rows) {
    var option = base();
    option.xAxis = valueAxis({max: 100, axisLabel: {color: INK.muted, formatter: '{value} %'}});
    option.yAxis = categoryAxis(_.pluck(rows, 'name'), {inverse: true});
    option.tooltip.formatter = function (params) {
        var row = rows[params[0].dataIndex];
        return _.str.sprintf(_t('%s<br/><b>%s h</b> de máquina · %s %% de 168 h'), _.escape(row.name), row.hours, row.pct);
    };
    option.series = [{
        type: 'bar', data: _.pluck(rows, 'pct'), barMaxWidth: 16,
        itemStyle: {color: SERIES[0], borderRadius: [0, 4, 4, 0]},
        label: {show: true, position: 'right', color: INK.secondary, formatter: function (params) {
            return rows[params.dataIndex].hours + ' h';
        }},
    }];
    return {
        option: option,
        hasData: _.some(rows, function (row) { return row.hours > 0; }),
        summary: _.map(rows, function (row) { return row.name + ': ' + row.hours + ' h'; }).join('; '),
    };
}

function success(rows) {
    var option = base();
    var keys = ['ok', 'partial', 'failed'];
    var labels = {ok: _t('OK'), partial: _t('Parcial'), failed: _t('Fallido')};
    option.legend = legend();
    option.grid.top = 30;
    option.xAxis = valueAxis({minInterval: 1});
    option.yAxis = categoryAxis(_.pluck(rows, 'name'), {inverse: true});
    option.series = _.map(keys, function (key, index) {
        return {
            type: 'bar', name: labels[key], stack: 'result', data: _.pluck(rows, key), barMaxWidth: 16,
            itemStyle: {
                color: STATUS[key], borderColor: INK.surface, borderWidth: 1,
                borderRadius: index === keys.length - 1 ? [0, 4, 4, 0] : 0,
            },
        };
    });
    return {
        option: option,
        hasData: _.some(rows, function (row) { return row.ok + row.partial + row.failed > 0; }),
        summary: _.map(rows, function (row) {
            return _.str.sprintf(_t('%s: %s OK, %s parcial, %s fallido'), row.name, row.ok, row.partial, row.failed);
        }).join('; '),
    };
}

function failure(rows) {
    var option = base();
    option.xAxis = valueAxis({minInterval: 1});
    option.yAxis = categoryAxis(_.pluck(rows, 'label'), {inverse: true});
    option.series = [{
        type: 'bar', name: _t('Intentos'), data: _.pluck(rows, 'count'), barMaxWidth: 16,
        itemStyle: {color: SERIES[0], borderRadius: [0, 4, 4, 0]},
        label: {show: true, position: 'right', color: INK.secondary},
    }];
    return {
        option: option,
        hasData: rows.length > 0,
        summary: _.map(rows, function (row) { return row.label + ': ' + row.count; }).join('; '),
    };
}

function grams(chart) {
    var option = base();
    option.legend = legend();
    option.grid.top = 30;
    option.grid.right = 8;
    option.xAxis = categoryAxis(chart.weeks, {axisLabel: {color: INK.muted}});
    option.yAxis = valueAxis({axisLabel: {color: INK.muted, formatter: '{value} g'}});
    option.series = _.map(chart.series, function (serie, index) {
        return {
            type: 'bar', name: serie.name, stack: 'grams', data: serie.data, barMaxWidth: 26,
            itemStyle: {color: SERIES[index % SERIES.length], borderColor: INK.surface, borderWidth: 1},
        };
    });
    var total = _.reduce(chart.series, function (sum, serie) {
        return sum + _.reduce(serie.data, function (acc, value) { return acc + value; }, 0);
    }, 0);
    return {
        option: option,
        hasData: total > 0,
        summary: _.str.sprintf(_t('%s g consumidos en 8 semanas'), Math.round(total)),
    };
}

return {
    build: function (trend, data) {
        switch (trend) {
            case 'success': return success(data.success_by_printer);
            case 'failure': return failure(data.failure_pareto);
            case 'grams': return grams(data.grams_by_purpose);
            default: return occupancy(data.occupancy);
        }
    },
};

});
