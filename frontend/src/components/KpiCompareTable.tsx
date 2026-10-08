// SPDX-License-Identifier: Apache-2.0
/** 报告「三、质量对比」前后指标表 —— 真实组件名 KpiCompareTable
 *  （原 ReportScreen 内联表格抽出，行为等价；差异见：比例键按百分数显示）。
 *
 * 口径：
 *  - 比例键（`*_ratio` / `*_rate`）→ 百分数 + 1 位小数（如 17.4%），变化列用「个百分点」；
 *  - 计数键（行数 / 列数 / `date_invalid_count` 等）→ 计数直显，变化列用带符号计数；
 *  - 未知键不隐藏，按计数直显（新增指标键不会从界面上消失）。
 */
import React from "react";
import { MetricValue } from "../api";
import { deltaMetricText, fmtMetricValue, metricLabel } from "../lib/format";

export interface KpiCompareTableProps {
  metrics: Record<string, MetricValue>;
}

export function KpiCompareTable({ metrics }: KpiCompareTableProps) {
  return (
    <table className="table table--numeric">
      <thead>
        <tr>
          <th>指标</th>
          <th className="num">清洗前</th>
          <th className="num">清洗后</th>
          <th className="num">变化</th>
        </tr>
      </thead>
      <tbody>
        {Object.entries(metrics).map(([key, m]) => (
          <tr key={key}>
            <td title={key}>{metricLabel(key)}</td>
            <td className="num">{fmtMetricValue(key, m.before)}</td>
            <td className="num">{fmtMetricValue(key, m.after)}</td>
            <td className="num">{deltaMetricText(key, m.before, m.after)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
