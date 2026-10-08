// SPDX-License-Identifier: Apache-2.0
/** 本地服务 API 封装（仅 127.0.0.1:8321，环回调用属设计内）。 */

const BASE = "http://127.0.0.1:8321/api";

/** 错误统一收敛为可读 message（后端 HTTPException detail 或网络错误）。
 *  缺陷修复：后端错误用 `detail.code` 分支（覆盖校验/说明不足），前端必须按码分流，
 *  禁止按文案匹配（见接口契约），故这里把 code 与 detail 一并带出。 */
export class ApiError extends Error {
  status?: number;
  /** 后端错误码（如 COVERAGE_BLOCKED / OVERRIDE_NOTE_REQUIRED）；无则为 undefined */
  code?: string;
  /** 后端原始 detail（字符串或对象） */
  detail?: ApiDetail | string;
  constructor(message: string, status?: number, code?: string, detail?: ApiDetail | string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

/** 后端 409 结构化 detail（见接口契约）。 */
export interface ApiDetail {
  code?: string;
  message?: string;
  /** COVERAGE_BLOCKED / OVERRIDE_NOTE_REQUIRED 时携带的未覆盖高危项 */
  uncovered_high?: UncoveredHighItem[];
}

/** 未覆盖的体检高危项（后端 engine.check_coverage 产出）。 */
export interface UncoveredHighItem {
  issue_name: string;
  label: string;
  severity: string;
  affected_rows: number;
  handlers: string[];
  message: string;
}

async function send<T>(path: string, init: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${BASE}${path}`, init);
  } catch {
    throw new ApiError("无法连接本地服务（127.0.0.1:8321）。请先启动后端：python -m app.server");
  }
  if (!resp.ok) {
    let message = `HTTP ${resp.status}`;
    let code: string | undefined;
    let detail: ApiDetail | string | undefined;
    try {
      const data = await resp.json();
      const raw = data?.detail;
      if (typeof raw === "string") {
        detail = raw;
        message = raw;
      } else if (raw && typeof raw === "object") {
        detail = raw as ApiDetail;
        code = typeof detail.code === "string" ? detail.code : undefined;
        if (typeof detail.message === "string" && detail.message) message = detail.message;
      }
      if (!code && typeof data?.error?.code === "string") code = data.error.code;
    } catch {
      /* 非 JSON 响应，保留默认 message */
    }
    throw new ApiError(message, resp.status, code, detail);
  }
  return resp.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  return send<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function get<T>(path: string): Promise<T> {
  return send<T>(path, { method: "GET" });
}

/* ------------------------------------------------------------------ *
 * 类型定义（与 backend/app/server/app.py 响应对齐）
 * ------------------------------------------------------------------ */

export interface HealthResult {
  status: string;
  version: string;
  schema_id: string;
  engine?: string;
  detectors?: string[];
  operations?: string[];
}

export interface ParseResult {
  thread_id: string;
  columns: string[];
  row_count: number;
  col_count: number;
  parsing_report: {
    encoding?: string;
    sheets?: string[];
    warnings?: string[];
  };
}

export interface ProfileIssue {
  issue_name: string;
  /** 中文名（后端 reporter.ISSUE_LABELS 同源；缺省时前端按 DETECTORS 兜底） */
  label?: string;
  severity: "high" | "medium" | "low";
  rows: number[];
  /** 该问题命中的列（单个；预填目标列用） */
  column?: string | null;
  /** 该问题命中的列（多个） */
  columns?: string[];
  /** 命中行数（数据量大时后端只给计数，rows 可能被截断） */
  rows_total?: number;
  /** 命中"样本值"（≤20 条，后端已脱敏；row 为原始数据 0 基行序）。
   *  前端**不得**按行号回索引原始数据——列被清洗后行号会错位，那是错值。 */
  samples?: IssueSample[];
  verbosity: number;
  /** 自动派生分数键：`<issue_name>_score` */
  [key: string]: unknown;
}

/** 问题命中样本（后端抽取 + 脱敏，只读）。 */
export interface IssueSample {
  row: number;
  column: string | null;
  value: string | null;
}

export interface EdaProfile {
  issues: ProfileIssue[];
  detector_errors: Array<{ issue_name: string; message: string }>;
}

export interface EdaResult {
  thread_id: string;
  profile: EdaProfile;
}

export interface PlanResult {
  thread_id: string;
  recipe_id: string;
  steps: Array<Record<string, unknown>>;
  description: string[];
  risk_flags: string[];
}

/** 越权放行（知情放行）留痕记录；确认响应回显 / 报告 `3_quality.overrides[]` 同形。 */
export interface OverrideRecord {
  ack: boolean;
  skipped: string[];
  note: string;
  at: string;
}

export interface ConfirmResult {
  confirmed: boolean;
  reason?: string;
  stage: string;
  /** 越权放行回显；无越权为 null */
  override?: OverrideRecord | null;
}

export interface TransformLogEntry {
  step: number;
  op: string;
  /** 该步作用对象 —— 列名（多列顿号分隔）或「全表」（无列参数时） */
  target?: string;
  rows_affected?: number;
  /** 目标列（历史字段；新契约用 target，保留兜底） */
  column?: string | null;
  skipped?: boolean;
  skip_reason?: string;
  sample_before?: unknown;
  sample_after?: unknown;
  [key: string]: unknown;
}

export interface ExecuteResult {
  columns: string[];
  rows: unknown[][];
  transform_log: TransformLogEntry[];
  data_ref: string;
}

/** 洗后指标值（比例键为 0~1 比例，计数键为绝对行数）。 */
export interface MetricValue {
  before: number | string;
  after: number | string;
}

/** 未达标项（对象数组，message 形如「金额残留: 273 行（占比 45.5%）」）。 */
export interface UnmetItem {
  key: string;
  before: number;
  after: number;
  rows: number | null;
  message: string;
}

/** 把历史字符串形态的 unmet 归一为对象数组形态（只在前端做兼容，不再分发字符串形态）。 */
export function normalizeUnmet(raw: unknown): UnmetItem[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item, i) => {
    if (typeof item === "string") {
      return { key: `legacy_${i}`, before: 0, after: 0, rows: null, message: item };
    }
    const o = (item ?? {}) as Partial<UnmetItem>;
    return {
      key: typeof o.key === "string" ? o.key : `unmet_${i}`,
      before: Number(o.before ?? 0),
      after: Number(o.after ?? 0),
      rows: o.rows === null || o.rows === undefined ? null : Number(o.rows),
      message: typeof o.message === "string" ? o.message : String(item),
    };
  });
}

export interface VerifyResult {
  thread_id: string;
  metrics: Record<string, MetricValue>;
  passed: boolean;
  /** 对象数组（旧字符串形态由 normalizeUnmet 兜底） */
  unmet: UnmetItem[];
  /** 质量校验结论（形如「未达标 1 项：日期非法（不可清洗）: 160 行」） */
  conclusion?: string;
  round?: number;
  retryable?: boolean;
  awaiting_hitl?: boolean;
}

export interface ReportResult {
  thread_id: string;
  format: "json" | "md";
  content: unknown;
}

export interface ExportResult {
  thread_id: string;
  path: string;
  format: string;
}

export interface RunStatusNode {
  node_name: string;
  attempt: number;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "AWAITING_HITL";
  started_at: string | null;
  ended_at: string | null;
}

export interface RunStatusResult {
  ok: boolean;
  run_id: string;
  stage: string;
  nodes: RunStatusNode[];
}

export interface RecipeImportResult {
  thread_id: string;
  recipe_id: string;
  steps: number;
}

/* ------------------------------------------------------------------ *
 * AI 辅助层（默认关；未启用时前端不得渲染任何 AI 入口）
 * ------------------------------------------------------------------ */

/** GET /api/ai/status —— 通道级状态，永不 500；不可达 → reachable=false + last_error。 */
export interface AiStatusResult {
  ok: boolean;
  enabled: boolean;
  /** "none" | "openai_compatible" */
  provider: string;
  model: string;
  /** 已配置端点地址（未配置为空串；只读展示用） */
  base_url?: string;
  timeout_s?: number;
  max_sample?: number;
  cache_enabled?: boolean;
  /** "shape_only" | "redacted_samples" */
  value_sharing: string;
  /** "on" | "masked" */
  column_name_sharing: string;
  key_configured: boolean;
  reachable: boolean;
  probed?: boolean;
  checked_at?: string | null;
  /** 无错时 null；"disabled" 表示未启用或未选 provider */
  last_error?: string | null;
  config_errors?: string[];
  /** 「会发送什么」预览（字段与形态标签样例，不含任何数据值） */
  preview?: AiPreview;
}

/** 设置页「会发送什么」预览（与实际请求体同源）。 */
export interface AiPreview {
  fields: string[];
  example: Record<string, unknown>;
  never_sent: string[];
  key_source: string;
  key_configured: boolean;
}

/** 单列建议（建议算子名必在既有算子目录内，值不由 AI 改）。 */
export interface AiAdviceItem {
  column: string;
  /** 受控语义类型（12 项枚举，表外视为不合规） */
  semantic_type: string;
  evidence: string[];
  suggested_ops: Array<{ op: string; params?: Record<string, unknown> }>;
  rationale: string;
  confidence: number;
  cached?: boolean;
}

export interface AiColumnAdviceResult {
  ok: boolean;
  thread_id: string;
  model: string;
  /** true = 无 AI 建议（reason ∈ disabled/unreachable/timeout/bad_schema） */
  degraded: boolean;
  reason?: string | null;
  advice: AiAdviceItem[];
  cached?: boolean;
}

export interface AiReportExplainResult {
  ok: boolean;
  thread_id: string;
  text: string;
  model: string;
  degraded: boolean;
  reason?: string | null;
  cached?: boolean;
  /** 固定免责注：「AI 生成，数值以上方表格为准」 */
  disclaimer: string;
}

export interface AiAcceptAdviceResult {
  ok: boolean;
  thread_id: string;
  appended?: boolean;
  reason?: string;
  recipe_step_index?: number;
  step?: Record<string, unknown>;
  steps?: number;
}

/* ------------------------------------------------------------------ *
 * 接口
 * ------------------------------------------------------------------ */

function fileToBase64(file: File): Promise<string> {
  return file.arrayBuffer().then((buf) => {
    const bytes = new Uint8Array(buf);
    let binary = "";
    const CHUNK = 0x8000;
    for (let i = 0; i < bytes.length; i += CHUNK) {
      binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
    }
    return btoa(binary);
  });
}

export const api = {
  health: (): Promise<HealthResult> =>
    fetch(`${BASE}/health`).then((r) => r.json()),

  /** 上传解析：浏览器本地读取数据流，原件不上传。 */
  parse: async (file: File): Promise<ParseResult> => {
    const content_b64 = await fileToBase64(file);
    return post<ParseResult>("/parse", {
      file_name: file.name,
      file_type: file.name.split(".").pop()?.toLowerCase() ?? "",
      file_size: file.size,
      content_b64,
    });
  },

  /** 体检：9 检测器全量跑。 */
  eda: (thread_id: string): Promise<EdaResult> =>
    post<EdaResult>("/eda", { thread_id }),

  /** 生成配方。 */
  plan: (
    thread_id: string,
    operations: Array<Record<string, unknown>>,
    recipe_name = "manual-plan",
  ): Promise<PlanResult> =>
    post<PlanResult>("/plan", { thread_id, operations, recipe_name }),

  /** 人工确认门。阻断状态下带 override 越权放行（ack=true + 说明 ≥5 字 + 跳过项名单）。 */
  confirm: (
    thread_id: string,
    approve: boolean,
    reason = "",
    override?: { ack: boolean; skipped: string[]; note: string },
  ): Promise<ConfirmResult> =>
    post<ConfirmResult>("/confirm", { thread_id, approve, reason, override }),

  /** 执行配方。 */
  execute: (thread_id: string): Promise<ExecuteResult> =>
    post<ExecuteResult>("/execute", { thread_id }),

  /** 前后校验。 */
  verify: (thread_id: string): Promise<VerifyResult> =>
    post<VerifyResult>("/verify", { thread_id }),

  /** 报告（json / md）。 */
  report: (thread_id: string, format: "json" | "md" = "json"): Promise<ReportResult> =>
    post<ReportResult>("/report", { thread_id, format }),

  /** 导出（csv / xlsx / ods / pdf / json / sql / template 七种主格式，附件同批落盘）。 */
  export: (thread_id: string, format: string, out_dir = ""): Promise<ExportResult> =>
    post<ExportResult>("/export", { thread_id, format, out_dir }),

  /** 节点级进度查询（轮询）。 */
  runStatus: (run_id: string): Promise<RunStatusResult> =>
    fetch(`${BASE}/run/${encodeURIComponent(run_id)}`).then((r) => r.json()),

  /** 配方导入（导入重放）。 */
  recipeImport: (
    thread_id: string,
    recipe_json: Record<string, unknown>,
  ): Promise<RecipeImportResult> =>
    post<RecipeImportResult>("/recipe-import", { thread_id, recipe_json }),

  /* ---------------- AI 辅助层（默认关，失败不阻塞） ---------------- */

  /** AI 通道状态；`probe=true`（设置页「测试连接」）才真探一次，默认只读缓存。 */
  aiStatus: (threadId = "", probe = false): Promise<AiStatusResult> =>
    get<AiStatusResult>(
      `/ai/status?tid=${encodeURIComponent(threadId)}${probe ? "&probe=true" : ""}`,
    ),

  /** 取列语义与方案建议（未指定 columns = 全部列；失败 → degraded=true，不阻塞）。 */
  aiColumnAdvice: (threadId: string, columns?: string[]): Promise<AiColumnAdviceResult> =>
    post<AiColumnAdviceResult>("/ai/column-advice", { thread_id: threadId, columns }),

  /** 体检报告人话版（只读，带免责注；失败 → degraded=true）。 */
  aiReportExplain: (threadId: string): Promise<AiReportExplainResult> =>
    post<AiReportExplainResult>("/ai/report-explain", { thread_id: threadId }),

  /** 把人工确认过的建议追加为配方步骤（只追加配方，不写数据、不执行）。 */
  aiAcceptAdvice: (
    threadId: string,
    column: string,
    op: string,
    params: Record<string, unknown> = {},
  ): Promise<AiAcceptAdviceResult> =>
    post<AiAcceptAdviceResult>("/ai/accept-advice", {
      thread_id: threadId,
      column,
      op,
      params,
    }),
};
