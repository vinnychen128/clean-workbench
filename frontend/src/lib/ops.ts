// SPDX-License-Identifier: Apache-2.0
/** 操作目录与检测器元数据 —— 与后端注册表对齐。
 *
 * - 9 检测器 issue_name：null / duplicate / outlier / format / amount / date /
 *   unit / identifier_column / mojibake
 * - 16 操作 op_name：行级 3 + 列级 5 + 单元格级 8
 * 前端以这些字符串作为配方 operations 的键（长期记忆：类名≠清单名，必须用清单字符串）。
 */

export type Level = "row" | "column" | "cell";

export interface OpSpec {
  op: string;
  level: Level;
  name: string;
  desc: string;
  /** 简化参数表单字段定义（用于选择面板） */
  fields: OpField[];
}

export interface OpField {
  key: string;
  label: string;
  type: "select" | "multi" | "text" | "number";
  /** select 的选项 */
  options?: Array<{ value: string; label: string }>;
  placeholder?: string;
  required?: boolean;
  /** 作用于列的下拉（type=select|multi 且 source="columns" 时从当前列取） */
  source?: "columns";
  /** 内联默认参数（如行级操作的 keep 默认值） */
  defaultValue?: string | number;
}

export const DETECTORS: Record<
  string,
  { name: string; desc: string; defaultOp: string }
> = {
  null: { name: "空值", desc: "缺失 / 空字符串", defaultOp: "cell_fill_missing" },
  duplicate: { name: "重复", desc: "整行或子集重复", defaultOp: "row_dedupe" },
  outlier: { name: "异常值", desc: "数值偏离分布", defaultOp: "row_delete" },
  format: { name: "格式", desc: "文本格式不一致", defaultOp: "cell_trim" },
  amount: { name: "金额", desc: "货币符号 / 千分位", defaultOp: "cell_amount_clean" },
  date: { name: "日期", desc: "多格式日期混杂", defaultOp: "cell_date_normalize" },
  unit: { name: "单位", desc: "单位混杂", defaultOp: "cell_unit_convert" },
  identifier_column: { name: "标识列", desc: "疑似主键列", defaultOp: "row_dedupe" },
  mojibake: { name: "乱码", desc: "编码错乱字符", defaultOp: "cell_text_replace" },
};

export const OP_DIRECTORY: OpSpec[] = [
  /* ---------------- 行级 3 ---------------- */
  {
    op: "row_dedupe", level: "row", name: "去重",
    desc: "按指定列子集（默认全列）删除重复行",
    fields: [
      { key: "subset", label: "判重列（留空 = 全列）", type: "multi", source: "columns" },
      { key: "keep", label: "保留", type: "select", defaultValue: "first",
        options: [{ value: "first", label: "首行" }, { value: "last", label: "末行" }] },
    ],
  },
  {
    op: "row_delete", level: "row", name: "删行",
    desc: "删除满足 列 = 值 的行",
    fields: [
      { key: "column", label: "条件列", type: "select", source: "columns", required: true },
      { key: "value", label: "匹配值", type: "text", placeholder: "如：已作废" },
    ],
  },
  {
    op: "row_keep", level: "row", name: "保行",
    desc: "仅保留 列 = 值 的行",
    fields: [
      { key: "column", label: "条件列", type: "select", source: "columns", required: true },
      { key: "value", label: "匹配值", type: "text", placeholder: "如：有效" },
    ],
  },

  /* ---------------- 列级 5 ---------------- */
  {
    op: "column_rename", level: "column", name: "列改名",
    desc: "重命名一列",
    fields: [
      { key: "column", label: "原列名", type: "select", source: "columns", required: true },
      { key: "new_name", label: "新列名", type: "text", required: true, placeholder: "如：客户名" },
    ],
  },
  {
    op: "column_delete", level: "column", name: "删列",
    desc: "删除一列或多列",
    fields: [
      { key: "columns", label: "待删列", type: "multi", source: "columns", required: true },
    ],
  },
  {
    op: "column_split", level: "column", name: "拆分列",
    desc: "按分隔符 / 正则拆分一列为多列",
    fields: [
      { key: "column", label: "目标列", type: "select", source: "columns", required: true },
      { key: "separator", label: "分隔符", type: "text", placeholder: "如：-" },
      { key: "new_columns", label: "新列名（逗号分隔）", type: "text", placeholder: "如：左,右" },
    ],
  },
  {
    op: "column_merge", level: "column", name: "合并列",
    desc: "多列按分隔符合并为一列",
    fields: [
      { key: "columns", label: "参与列", type: "multi", source: "columns", required: true },
      { key: "separator", label: "分隔符", type: "text", defaultValue: "_" },
      { key: "new_name", label: "新列名", type: "text", placeholder: "默认：列名拼接" },
    ],
  },
  {
    op: "column_derive", level: "column", name: "派生列",
    desc: "基于 {列名} 表达式新建列（支持四则运算）",
    fields: [
      { key: "new_column", label: "新列名", type: "text", required: true, placeholder: "如：金额_元" },
      { key: "expression", label: "表达式", type: "text", required: true, placeholder: "如：{单价} * {数量}" },
    ],
  },

  /* ---------------- 单元格级 8 ---------------- */
  {
    op: "cell_trim", level: "cell", name: "去空格",
    desc: "去除单元格首尾空白",
    fields: [
      { key: "columns", label: "目标列", type: "multi", source: "columns", required: true },
    ],
  },
  {
    op: "cell_fullwidth", level: "cell", name: "全角转半角",
    desc: "全角数字 / 字母 / 标点转半角",
    fields: [
      { key: "columns", label: "目标列", type: "multi", source: "columns", required: true },
    ],
  },
  {
    op: "cell_unit_convert", level: "cell", name: "单位换算",
    desc: "数值列单位转换（内置常用换算表）；目标单位填「纯数值」则改为剥离单位、只留数值（用于 3件 / 5台 这类数字与量词粘连）",
    fields: [
      { key: "column", label: "目标列", type: "select", source: "columns", required: true },
      { key: "from", label: "原单位", type: "text", required: true, placeholder: "如：MPa；剥离模式可填被剥离的量词，如：件" },
      { key: "to", label: "目标单位", type: "text", required: true, placeholder: "如：bar；填「纯数值」= 剥离单位只留数值" },
    ],
  },
  {
    op: "cell_case", level: "cell", name: "大小写",
    desc: "文本转大写 / 小写 / 首字母大写",
    fields: [
      { key: "columns", label: "目标列", type: "multi", source: "columns", required: true },
      { key: "mode", label: "模式", type: "select", defaultValue: "upper",
        options: [
          { value: "upper", label: "大写" },
          { value: "lower", label: "小写" },
          { value: "title", label: "首字母大写" },
        ] },
    ],
  },
  {
    op: "cell_date_normalize", level: "cell", name: "日期规范化",
    desc: "多格式日期统一为 YYYY-MM-DD",
    fields: [
      { key: "column", label: "目标列", type: "select", source: "columns", required: true },
    ],
  },
  {
    op: "cell_amount_clean", level: "cell", name: "金额清洗",
    desc: "去货币符号 / 千分位，统一为纯数字",
    fields: [
      { key: "column", label: "目标列", type: "select", source: "columns", required: true },
    ],
  },
  {
    op: "cell_text_replace", level: "cell", name: "文本替换",
    desc: "整词 / 正则替换",
    fields: [
      { key: "columns", label: "目标列", type: "multi", source: "columns", required: true },
      { key: "old", label: "查找", type: "text", required: true, placeholder: "如：待删" },
      { key: "new", label: "替换为", type: "text", placeholder: "留空 = 删除" },
      { key: "regex", label: "正则", type: "select", defaultValue: "false",
        options: [{ value: "false", label: "否" }, { value: "true", label: "是" }] },
    ],
  },
  {
    op: "cell_fill_missing", level: "cell", name: "缺失值填充",
    desc: "按常量 / 前值 / 后值 / 均值填充空值",
    fields: [
      { key: "column", label: "目标列", type: "select", source: "columns", required: true },
      { key: "method", label: "方式", type: "select", defaultValue: "constant",
        options: [
          { value: "constant", label: "常量" },
          { value: "ffill", label: "前值填充" },
          { value: "bfill", label: "后值填充" },
          { value: "mean", label: "列均值" },
        ] },
      { key: "value", label: "常量值", type: "text", placeholder: "method=constant 时生效" },
    ],
  },
];

export const LEVELS: Array<{ value: Level; label: string }> = [
  { value: "row", label: "行级" },
  { value: "column", label: "列级" },
  { value: "cell", label: "单元格级" },
];

/** 中文操作名（报告 / 日志展示用）。 */
export function opLabel(op: string): string {
  return OP_DIRECTORY.find((o) => o.op === op)?.name ?? op;
}

export function levelLabel(level: Level): string {
  return LEVELS.find((l) => l.value === level)?.label ?? level;
}

/* ================================================================== *
 * 步骤配置状态机
 * ================================================================== */

/** 配方中的一步（前端编排态）：op 字符串 + 参数集。 */
export interface PickedOp {
  op: string;
  params: Record<string, unknown>;
}

/** 步骤配置状态：pending=必填项缺（待配置） ready=可执行 unknown=操作未知 risky=计划期风险 */
export type StepStatus = "pending" | "ready" | "unknown" | "risky";

export function specOf(op: string): OpSpec | undefined {
  return OP_DIRECTORY.find((o) => o.op === op);
}

/** 空值判定：undefined / null / 空串 / 仅空白 / 空数组。 */
export function isBlank(v: unknown): boolean {
  if (v === undefined || v === null) return true;
  if (typeof v === "string") return v.trim() === "";
  if (Array.isArray(v)) return v.length === 0;
  return false;
}

/** 该字段是否必填（无 defaultValue 且未声明 required 的 select 若来自 columns 也视为必填）。 */
export function isFieldRequired(field: OpField): boolean {
  if (field.required) return true;
  if (field.source === "columns" && field.type !== "text" && field.type !== "number") {
    return field.defaultValue === undefined;
  }
  return false;
}

/** 返回未满足的必填字段（空数组 = 该步可执行）。 */
export function missingRequiredFields(picked: PickedOp): OpField[] {
  const spec = specOf(picked.op);
  if (!spec) return [];
  return spec.fields.filter(
    (f) => isFieldRequired(f) && isBlank(picked.params[f.key]),
  );
}

/** 取参数值（带内联默认值兜底）。 */
export function paramValue(picked: PickedOp, key: string): unknown {
  const v = picked.params[key];
  if (!isBlank(v)) return v;
  return specOf(picked.op)?.fields.find((f) => f.key === key)?.defaultValue;
}

/** 新建一步时按字段内联默认值初始化参数。 */
export function initParams(op: string): Record<string, unknown> {
  const spec = specOf(op);
  const params: Record<string, unknown> = {};
  for (const f of spec?.fields ?? []) {
    if (f.defaultValue !== undefined) params[f.key] = f.defaultValue;
  }
  return params;
}

/** 风险标记是否归属第 idx（0-based）步：后端 risk_flags 形如「第 2 步 ...」。 */
export function riskFlagMatchesStep(flag: string, idx: number): boolean {
  const n = idx + 1;
  return (
    flag.includes(`第 ${n} 步`) ||
    flag.includes(`第${n}步`) ||
    flag.includes(`step ${n}`) ||
    flag.includes(`step_${n}`) ||
    flag.includes(`#${n}`)
  );
}

export interface DerivedRecipe {
  statuses: StepStatus[];
  /** 未配置完成的步序号（0-based，按执行顺序） */
  pendingIndexes: number[];
  /** 未识别的操作名 */
  unknownOps: string[];
  riskyIndexes: number[];
  /** 是否全部可执行（unknown/risky 也允许执行，仅 pending 阻断） */
  runnable: boolean;
}

/**
 * 单一状态派生函数：屏 4 步卡标记、屏 4 页脚阻断、屏 5 影响统计共用同一真值来源。
 */
export function deriveRecipe(
  picked: PickedOp[],
  riskFlags: string[] = [],
): DerivedRecipe {
  const statuses: StepStatus[] = [];
  const pendingIndexes: number[] = [];
  const unknownOps: string[] = [];
  const riskyIndexes: number[] = [];

  picked.forEach((p, i) => {
    const spec = specOf(p.op);
    if (!spec) {
      statuses.push("unknown");
      unknownOps.push(p.op);
      return;
    }
    if (missingRequiredFields(p).length > 0) {
      statuses.push("pending");
      pendingIndexes.push(i);
      return;
    }
    if (riskFlags.some((f) => riskFlagMatchesStep(f, i))) {
      statuses.push("risky");
      riskyIndexes.push(i);
      return;
    }
    statuses.push("ready");
  });

  return {
    statuses,
    pendingIndexes,
    unknownOps,
    riskyIndexes,
    runnable: pendingIndexes.length === 0 && picked.length > 0,
  };
}

/** 兼容旧调用点的薄封装。 */
export function deriveStepStatus(
  picked: PickedOp[],
  riskFlags: string[] = [],
): StepStatus[] {
  return deriveRecipe(picked, riskFlags).statuses;
}

export const STEP_STATUS_LABEL: Record<StepStatus, string> = {
  pending: "待配置",
  ready: "已就绪",
  unknown: "未知操作",
  risky: "需重点确认",
};

/** 阻断文案：列出待配置步号与各自缺的必填字段，供屏 4 页脚与就地错误提示共用。 */
export function pendingBlockerText(picked: PickedOp[], indexes: number[]): string {
  const detail = indexes
    .map((i) => {
      const missing = missingRequiredFields(picked[i])
        .map((f) => f.label)
        .join("、");
      return `第 ${i + 1} 步（${opLabel(picked[i].op)}）缺 ${missing || "必填参数"}`;
    })
    .join("；");
  return `还有 ${indexes.length} 步未配置完成：${detail}。补齐后才能生成配方。`;
}

/** 人话操作摘要（步卡标题副文案 / 摘要条）。 */
export function opSummary(picked: PickedOp): string {
  const spec = specOf(picked.op);
  if (!spec) return picked.op;
  const parts: string[] = [];
  for (const f of spec.fields) {
    const v = picked.params[f.key];
    if (isBlank(v)) continue;
    const text = Array.isArray(v) ? v.join("、") : String(v);
    parts.push(`${f.label}: ${text}`);
  }
  return parts.length ? parts.join(" · ") : spec.desc;
}

/* ================================================================== *
 * 建议步骤预填目标列
 * ================================================================== */

/** 该操作是否有"目标列"类字段（用于判断是否需要提示用户挑列）。 */
function hasColumnField(spec: OpSpec): boolean {
  return spec.fields.some((f) => f.key === "column" || f.key === "columns");
}

/**
 * 由体检问题的列信息推导预填参数。
 *
 * 规则（不猜）：
 * - 唯一确定列（问题只涉及 1 列）→ 单列字段 `column` 与多列字段 `columns` 都填该列；
 * - 多列问题 → 只填多列字段 `columns`（全部命中列），单列字段留空并由 note 提示用户选；
 * - 无列信息 → 不预填，若有目标列字段则给一句可操作提示（不得默认第一列）。
 */
export function prefillForIssue(
  op: string,
  issueColumns: readonly string[],
): { params: Record<string, unknown>; note: string } {
  const spec = specOf(op);
  const cols = Array.from(
    new Set((issueColumns ?? []).map((c) => String(c ?? "").trim()).filter((c) => c !== "")),
  );
  const params: Record<string, unknown> = {};
  if (!spec) return { params, note: "" };
  if (cols.length === 0) {
    return {
      params,
      note: hasColumnField(spec) ? "该问题未给出具体列，请在步卡选择要处理的列。" : "",
    };
  }
  let needPick = false;
  for (const f of spec.fields) {
    if (f.type !== "select" && f.type !== "multi") continue;
    if (f.key === "column") {
      if (cols.length === 1) params[f.key] = cols[0];
      else needPick = true;
    } else if (f.key === "columns") {
      params[f.key] = cols;
    }
  }
  return {
    params,
    note: needPick ? `该问题涉及列：${cols.join("/")}，请选择要处理的列。` : "",
  };
}
