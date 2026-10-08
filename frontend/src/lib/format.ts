// SPDX-License-Identifier: Apache-2.0
/** 显示口径统一：比例类数值一律「百分数 + 1 位小数」（如 17.4%），
 *  与报告 Markdown / 对账脚本 `scripts/check_residual_dirt.py` 同口径；
 *  同一数值在不同界面**不得**出现两种口径，故所有比例显示都走本文件。
 *
 *  分母口径：
 *  - 洗后残留指标（`*_ratio`）的分母 = **洗后总行数**（session.rowsAfter）；
 *  - 体检阶段（洗前）命中占比的分母 = 本次扫描的总行数（洗前数据规模）。
 *    两者用途不同，不得互相冒充：洗前的分母写「本次扫描 N 行」，洗后写「洗后 N 行」。
 */
import { fmtNum } from "../components/ui/primitives";

/** 比例显示固定 1 位小数（0.442 → 44.2%）。 */
export const PCT_DIGITS = 1;

/** 0~1 比例 → 百分数（1 位小数）；非数值返回「—」。 */
export function fmtPct(ratio: unknown): string {
  const n = typeof ratio === "number" ? ratio : Number(ratio);
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(PCT_DIGITS)}%`;
}

/** 计数 / 总数 → 百分数；分母 ≤0 或非法时返回 null（调用方决定显示「—」）。 */
export function pctOf(count: unknown, total: unknown): string | null {
  const c = typeof count === "number" ? count : Number(count);
  const t = typeof total === "number" ? total : Number(total);
  if (!Number.isFinite(c) || !Number.isFinite(t) || t <= 0) return null;
  return fmtPct(c / t);
}

/** 比例键识别：洗后指标里的比例类键（0~1）。 */
export function isRatioMetricKey(key: string): boolean {
  return /_ratio$/.test(key) || /_rate$/.test(key) || key === "ratio";
}

/** 指标值显示：比例键 → 百分数 + 1 位小数；计数键 → 计数直显。 */
export function fmtMetricValue(key: string, v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (isRatioMetricKey(key)) return fmtPct(v);
  return fmtNum(v);
}

/** 指标变化文案：比例键用「个百分点」，计数键用带符号计数；无变化「持平」。 */
export function deltaMetricText(key: string, before: unknown, after: unknown): string {
  if (before === null || before === undefined || after === null || after === undefined) return "—";
  const b = Number(before);
  const a = Number(after);
  if (!Number.isFinite(b) || !Number.isFinite(a)) return "—";
  const d = a - b;
  if (d === 0) return "持平";
  if (isRatioMetricKey(key)) return `${d > 0 ? "+" : ""}${(d * 100).toFixed(PCT_DIGITS)} 个百分点`;
  return `${d > 0 ? "+" : ""}${fmtNum(d)}`;
}

/** 洗后残留五键的中文名（契约键名，不得改名）。 */
export const METRIC_LABELS: Record<string, string> = {
  rows: "数据行数",
  columns: "数据列数",
  empty_ratio: "空值率",
  dup_ratio: "重复率",
  amount_dirty_ratio: "金额残留比例",
  date_nonstandard_ratio: "日期非标准格式残留比例",
  date_invalid_count: "日期非法（不可清洗）行数",
  unit_dirty_ratio: "单位残留 / 混用比例",
  numeric_dirty_ratio: "数量非数值残留比例",
};

/** 指标键 → 中文名（报告「三、质量对比」用）；未知键显示原名，不隐藏。 */
export function metricLabel(key: string): string {
  return METRIC_LABELS[key] ?? key;
}

/** 界面文本：去掉后端 conclusion / message / reason 里的 Markdown 强调标记后显示。
 *
 *  后端 `1_profile.conclusion` / `3_quality.conclusion` / `unhandled[i].reason` 里带 `**重点**`
 *  这类标记（那是写进 Markdown 报告的语法），界面按纯文本渲染会把星号一起显示出来。
 *  首屏结论口径是纯文本形如「质量校验未达标 3 项（明细见「三、质量对比」）」，
 *  故这里**只摘标记符、不改一个字**；Markdown 原文视图仍显示后端原样文本。
 */
export function uiText(s: unknown): string {
  return String(s ?? "")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/__(.+?)__/g, "$1");
}

/** 未达标项 message / 结论 / 未处理原因的界面口径。
 *
 *  后端对少数无中文名的指标会给出 `<内部键>: <数> > <数>` 形态（如 `dup_ratio: 0.1667 > 0.0`），
 *  裸小数 + 内部键名直接用会在报告屏出现「无单位小数」（违反「不出现无单位裸小数」）。
 *  这里**只归一「比例类指标键 + 比较式」这一种片段**：
 *  - 键名换中文名（单一来源 `METRIC_LABELS`，与报告「三、质量对比」表同一份）；
 *  - 比较式两边数值按百分数 + 1 位小数。
 *  其余任何一个字**原样保留**（含带「行」「占比」等中文的 message），不改写后端文案内容。
 */
export function unmetMessageText(raw: unknown): string {
  const s = uiText(raw);
  return s.replace(
    /([A-Za-z_][A-Za-z0-9_]*)\s*[:：]\s*(-?\d+(?:\.\d+)?)\s*([>≥<≤])\s*(-?\d+(?:\.\d+)?)/g,
    (whole, key: string, a: string, op: string, b: string) => {
      if (!isRatioMetricKey(key)) return whole;
      return `${metricLabel(key)}：${fmtPct(Number(a))} ${op} ${fmtPct(Number(b))}`;
    },
  );
}
