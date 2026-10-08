// SPDX-License-Identifier: Apache-2.0
/** 会话状态中枢：把散落的状态收敛为单一 useSession()。
 *  字段名与旧实现保持一致，屏幕组件只读状态 + 调用动作，不各自持有业务状态。 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiDetail,
  ApiError,
  ConfirmResult,
  EdaResult,
  ExecuteResult,
  HealthResult,
  ParseResult,
  PlanResult,
  RunStatusNode,
  UncoveredHighItem,
  VerifyResult,
  api,
} from "../api";
import { DETECTORS, DerivedRecipe, PickedOp, deriveRecipe, initParams } from "../lib/ops";
import { appendHistory } from "../components/HistoryPanel";

/** 本机时钟（供历史记录使用，不用外部服务时间）。 */
const clockNow = () => new Date().toLocaleTimeString("zh-CN", { hour12: false });

export type ScreenKey = "upload" | "eda" | "recipe" | "hitl" | "execute" | "report" | "export";

export const SCREENS: Array<{ key: ScreenKey; label: string }> = [
  { key: "upload", label: "上传" },
  { key: "eda", label: "体检" },
  { key: "recipe", label: "配方" },
  { key: "hitl", label: "确认" },
  { key: "execute", label: "执行" },
  { key: "report", label: "报告" },
  { key: "export", label: "导出" },
];

export interface ExportRecord {
  format: string;
  path: string;
  extra: string[];
  at: string;
}

/** 体检问题 → 可覆盖该问题的清洗操作集合（确认门「高危是否达标」判定依据）。
 *
 *  **单一来源**：`backend/app/report/reporter.py::HANDLED_BY_OPS`（+ `ISSUE_LABELS`）；
 *  本表必须与后端逐项一致（契约测试 `backend/tests/test_contract_mapping.py` 把关），
 *  出现第二份同类清单即为缺陷——改这里必须同时改后端那一份。 */
const ISSUE_HANDLERS: Record<string, string[]> = {
  null: ["cell_fill_missing", "row_delete", "row_keep"],
  duplicate: ["row_dedupe"],
  outlier: ["row_delete", "row_keep"],
  format: ["cell_trim", "cell_fullwidth", "cell_case", "cell_text_replace"],
  amount: ["cell_amount_clean", "cell_text_replace"],
  date: ["cell_date_normalize", "cell_text_replace"],
  unit: ["cell_unit_convert", "cell_text_replace"],
  identifier_column: ["row_dedupe", "row_keep"],
  mojibake: ["cell_text_replace"],
};

/** 未达标高危项明细（前端 riskGate 展示用；与后端 check_coverage 的 uncovered_high 同字段口径）。 */
export interface UncoveredHighBrief {
  issue_name: string;
  label: string;
  severity: string;
  affected_rows: number;
  handlers: string[];
  message: string;
  /** 前端给的建议步骤（后端 uncovered_high 无该字段，仅用于就地提示） */
  suggested_op: string;
}

/** 覆盖校验阻断态：后端 409 COVERAGE_BLOCKED 的 detail，或前端本地预判。 */
export interface CoverageBlock {
  message: string;
  uncoveredHigh: UncoveredHighItem[];
}

/** 确认门风险闸门（缺陷修复③）：把体检高危项纳入风险计数；高危未达标则阻断放行。 */
export interface RiskGate {
  /** 体检检出的高危项总数 */
  edaHighCount: number;
  /** 已被配方操作覆盖（达标）的高危项数 */
  coveredHighCount: number;
  /** 未被配方覆盖（未达标）的高危项数 */
  uncoveredHighCount: number;
  /** 未达标高危项明细（含中文名、可用操作与建议步骤） */
  uncoveredHighIssues: UncoveredHighBrief[];
  /** 确认门风险项计数 = 配方风险步数 + 体检高危项数 */
  riskItemCount: number;
  /** 是否阻断确认门放行（存在未达标高危项） */
  blocked: boolean;
}

export interface Session {
  screen: ScreenKey;
  goTo: (s: ScreenKey) => void;
  reachable: (s: ScreenKey) => boolean;

  // 服务
  health: HealthResult | null;
  healthError: string;

  // 上传解析
  fileName: string;
  fileSize: number;
  threadId: string;
  columns: string[];
  rowCount: number;
  colCount: number;
  parsingReport: ParseResult["parsing_report"] | null;
  parseBusy: boolean;
  parse: (file: File) => Promise<void>;

  // 体检
  eda: EdaResult | null;
  edaBusy: boolean;
  runEda: () => Promise<void>;

  // 配方编排
  picked: PickedOp[];
  derived: DerivedRecipe;
  /** 确认门风险闸门（缺陷修复③）：体检高危项纳入风险计数，未达标则阻断放行 */
  riskGate: RiskGate;
  /** 可带预填参数加入步骤（体检问题 → 目标列预填）；不传 params 时仅有内联默认值 */
  addOp: (op: string, params?: Record<string, unknown>) => void;
  updateParam: (index: number, key: string, value: unknown) => void;
  removeOp: (index: number) => void;
  moveOp: (index: number, dir: -1 | 1) => void;
  resetOps: () => void;
  plan: PlanResult | null;
  planBusy: boolean;
  submitPlan: () => Promise<void>;

  // 人工确认
  confirmResult: ConfirmResult | null;
  confirmBusy: boolean;
  /** 覆盖校验阻断态（后端 409 COVERAGE_BLOCKED 或前端预判）；无阻断为 null */
  coverageBlock: CoverageBlock | null;
  /** 说明不足的就地提示（后端 OVERRIDE_NOTE_REQUIRED 或前端校验） */
  overrideNoteError: string;
  clearOverrideHint: () => void;
  /** 越权放行时带 override（ack=true + 说明 ≥5 字 + 跳过项名单）重发 /api/confirm */
  decide: (
    approve: boolean,
    reason: string,
    override?: { ack: boolean; skipped: string[]; note: string },
  ) => Promise<void>;

  // 执行
  exec: ExecuteResult | null;
  execBusy: boolean;
  execError: string;
  /** 已发起的执行次数（失败重试计数用） */
  execAttempt: number;
  /** 节点流水线是否处于轮询中（1.5s 间隔） */
  polling: boolean;
  /** 执行是否已成功产出结果且无失败节点（决定「查看报告」是否可用） */
  canViewReport: boolean;
  nodes: RunStatusNode[];
  runStage: string;
  startExecute: () => Promise<void>;
  refreshRun: () => Promise<void>;

  // 校验与报告
  verify: VerifyResult | null;
  /** 洗后总行数（洗后比例指标的分母；与对账脚本 check_residual_dirt.py 同口径） */
  rowsAfter: number;
  reportMd: string;
  reportJson: unknown;
  reportBusy: boolean;
  loadVerify: () => Promise<void>;
  /** 取报告；返回本次获取到的内容（md 为字符串），便于调用方一次性落本地文件。 */
  loadReport: (format: "json" | "md") => Promise<unknown>;

  // 导出
  exports: ExportRecord[];
  exportBusy: string;
  /** 导出。busyKey 用于区分同一格式被多个入口触发时的加载态（缺陷修复②）。 */
  doExport: (
    format: string,
    opts?: { outDir?: string; attachments?: boolean; busyKey?: string },
  ) => Promise<void>;

  // 提示
  error: string;
  info: string;
  setError: (s: string) => void;
  setInfo: (s: string) => void;
  reset: () => void;
}

function messageOf(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

export function useSession(): Session {
  const [screen, setScreen] = useState<ScreenKey>("upload");
  const [health, setHealth] = useState<HealthResult | null>(null);
  const [healthError, setHealthError] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  const [fileName, setFileName] = useState("");
  const [fileSize, setFileSize] = useState(0);
  const [threadId, setThreadId] = useState("");
  const [columns, setColumns] = useState<string[]>([]);
  const [rowCount, setRowCount] = useState(0);
  const [colCount, setColCount] = useState(0);
  const [parsingReport, setParsingReport] = useState<ParseResult["parsing_report"] | null>(null);
  const [parseBusy, setParseBusy] = useState(false);

  const [eda, setEda] = useState<EdaResult | null>(null);
  const [edaBusy, setEdaBusy] = useState(false);

  const [picked, setPicked] = useState<PickedOp[]>([]);
  const [plan, setPlan] = useState<PlanResult | null>(null);
  const [planBusy, setPlanBusy] = useState(false);

  const [confirmResult, setConfirmResult] = useState<ConfirmResult | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  /** 覆盖校验阻断态（后端 409 COVERAGE_BLOCKED / 前端预判）与说明不足提示。 */
  const [coverageBlock, setCoverageBlock] = useState<CoverageBlock | null>(null);
  const [overrideNoteError, setOverrideNoteError] = useState("");

  const [exec, setExec] = useState<ExecuteResult | null>(null);
  const [execBusy, setExecBusy] = useState(false);
  const [execError, setExecError] = useState("");
  const [nodes, setNodes] = useState<RunStatusNode[]>([]);
  const [runStage, setRunStage] = useState("");
  /** 执行尝试次数（失败重试上限 3 次的计数来源）与轮询开关。 */
  const [execAttempt, setExecAttempt] = useState(0);
  const [polling, setPolling] = useState(false);
  const pollTicks = useRef(0);
  /** 执行请求在途守卫（缺陷修复）：state 在同一轮渲染内不会立即更新，
   *  React 18 StrictMode 双挂载 / 重进屏会绕过 execBusy 守卫重复提交，故用 ref 同步判重。 */
  const execInFlight = useRef(false);
  /** 缺陷修复②（执行口径一致）：配方代次 / 已执行代次。
   *  同一线程内 recipe_id 恒定（后端 f"recipe-{len(thread_id)}"），无法充当新鲜度标识，
   *  故改用前端代次：每次「生成配方」递增，执行结果只有与其代次相同才算新鲜。 */
  const planSeq = useRef(0);
  const execSeq = useRef(-1);

  const [verify, setVerify] = useState<VerifyResult | null>(null);
  const [reportMd, setReportMd] = useState("");
  const [reportJson, setReportJson] = useState<unknown>(null);
  const [reportBusy, setReportBusy] = useState(false);

  const [exports, setExports] = useState<ExportRecord[]>([]);
  const [exportBusy, setExportBusy] = useState("");

  const derived = useMemo(
    () => deriveRecipe(picked, plan?.risk_flags ?? []),
    [picked, plan?.risk_flags],
  );

  /* ---------------- 确认门风险闸门（缺陷修复③） ----------------
     风险项计数 = 配方风险步数 + 体检高危项数（高危不再只显示在体检屏）；
     存在「体检高危但配方未覆盖」的项时判定未达标，阻断确认门放行。
     判据与后端 `check_coverage` 同一份（`reporter.HANDLED_BY_OPS`，见 ISSUE_HANDLERS 注释）。 */
  const riskGate = useMemo<RiskGate>(() => {
    const highIssues = (eda?.profile?.issues ?? []).filter((it) => it.severity === "high");
    const pickedOps = picked.map((p) => p.op);
    /** 命中行的行数：rows_total 优先（数据量大时后端可能只给计数），否则按 rows 长度。 */
    const affectedOf = (rows: number[] | undefined, rowsTotal: unknown): number => {
      const total = Number(rowsTotal);
      if (Number.isFinite(total) && total > 0) return total;
      return (rows ?? []).length;
    };
    const handlersFor = (issueName: string): string[] => {
      const spec = DETECTORS[issueName];
      const suggested = spec?.defaultOp ? [spec.defaultOp] : [];
      return [...(ISSUE_HANDLERS[issueName] ?? []), ...suggested];
    };
    const uncovered = highIssues.filter((it) => {
      if (handlersFor(it.issue_name).length === 0) return true;
      if (affectedOf(it.rows, it.rows_total) === 0) return false; // 体检未命中：不判（与后端 check_coverage 同口径）
      const handlers = handlersFor(it.issue_name);
      return !handlers.some((op) => pickedOps.includes(op));
    });
    return {
      edaHighCount: highIssues.length,
      coveredHighCount: highIssues.length - uncovered.length,
      uncoveredHighCount: uncovered.length,
      uncoveredHighIssues: uncovered.map((it) => {
        /* 界面问题名统一取前端检测器注册表（lib/ops.ts::DETECTORS），
           与体检屏 / 问题表 / 报告屏同一份；后端 label 只作兜底，避免同一问题在两屏两个名字。 */
        const label = DETECTORS[it.issue_name]?.name ?? it.label ?? it.issue_name;
        const affected = affectedOf(it.rows, it.rows_total);
        const handlers = ISSUE_HANDLERS[it.issue_name] ?? [];
        return {
          issue_name: it.issue_name,
          label,
          severity: it.severity,
          affected_rows: affected,
          handlers,
          message:
            `高危问题「${label}」未被配方覆盖（${affected} 行）：` +
            `可用操作 ${handlers.length ? handlers.join("/") : "无"}`,
          suggested_op: DETECTORS[it.issue_name]?.defaultOp ?? "",
        };
      }),
      riskItemCount: derived.riskyIndexes.length + highIssues.length,
      blocked: uncovered.length > 0,
    };
  }, [eda, picked, derived.riskyIndexes.length]);

  /* ---------------- 服务健康 ---------------- */
  useEffect(() => {
    api
      .health()
      .then((h) => {
        setHealth(h);
        setHealthError("");
      })
      .catch((e) => setHealthError(messageOf(e)));
  }, []);

  /* ---------------- 可跳转判定 ---------------- */
  const reachable = useCallback(
    (s: ScreenKey): boolean => {
      switch (s) {
        case "upload":
        case "eda":
        case "recipe":
          return true;
        case "hitl":
          return !!plan;
        case "execute":
          return !!plan && !!confirmResult?.confirmed;
        case "report":
        case "export":
          return !!exec;
        default:
          return false;
      }
    },
    [plan, confirmResult, exec],
  );

  const goTo = useCallback(
    (s: ScreenKey) => {
      if (!reachable(s)) return;
      setError("");
      setScreen(s);
      window.scrollTo({ top: 0 });
    },
    [reachable],
  );

  /* ---------------- 上传解析 ---------------- */
  const parse = useCallback(async (file: File) => {
    setParseBusy(true);
    setError("");
    setInfo("");
    try {
      const r = await api.parse(file);
      setFileName(file.name);
      setFileSize(file.size);
      setThreadId(r.thread_id);
      setColumns(r.columns ?? []);
      setRowCount(r.row_count ?? 0);
      setColCount(r.col_count ?? (r.columns?.length ?? 0));
      setParsingReport(r.parsing_report ?? null);
      // 换文件即重置下游链路，避免旧配方/旧结果串台
      setEda(null);
      setPicked([]);
      setPlan(null);
      setConfirmResult(null);
      setExec(null);
      setVerify(null);
      setReportMd("");
      setReportJson(null);
      setExports([]);
      appendHistory({
        thread_id: r.thread_id,
        file_name: file.name,
        row_count: r.row_count ?? 0,
        col_count: r.col_count ?? (r.columns?.length ?? 0),
        created_at: clockNow(),
        completed: false,
      });
      setInfo(`已解析 ${r.row_count} 行 × ${(r.columns ?? []).length} 列，原件未上传（仅本机读取）。`);
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setParseBusy(false);
    }
  }, []);

  /* ---------------- 体检 ---------------- */
  const runEda = useCallback(async () => {
    if (!threadId) {
      setError("请先上传并解析一个数据文件。");
      return;
    }
    setEdaBusy(true);
    setError("");
    try {
      const r = await api.eda(threadId);
      setEda(r);
      setScreen("eda");
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setEdaBusy(false);
    }
  }, [threadId]);

  /* ---------------- 配方编排 ---------------- */
  /** 可带预填参数加入步骤（体检问题的目标列预填）；预填值覆盖内联默认值。 */
  const addOp = useCallback((op: string, params?: Record<string, unknown>) => {
    setPlan(null);
    setPicked((prev) => [
      ...prev,
      { op, params: { ...initParams(op), ...(params ?? {}) } },
    ]);
  }, []);

  const updateParam = useCallback((index: number, key: string, value: unknown) => {
    setPicked((prev) =>
      prev.map((p, i) => (i === index ? { ...p, params: { ...p.params, [key]: value } } : p)),
    );
  }, []);

  const removeOp = useCallback((index: number) => {
    setPlan(null);
    setPicked((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const moveOp = useCallback((index: number, dir: -1 | 1) => {
    setPlan(null);
    setPicked((prev) => {
      const next = [...prev];
      const target = index + dir;
      if (target < 0 || target >= next.length) return prev;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }, []);

  const resetOps = useCallback(() => {
    setPicked([]);
    setPlan(null);
  }, []);

  /** 缺陷修复②：把「配方之后」的结果态整体作废（执行结果 / 校验 / 报告）。
   *  新配方或新一轮确认时调用，确保执行屏必然重跑、报告屏必然重建，
   *  杜绝确认门显 6 步、执行屏 / 报告 / 导出仍显上一轮 1 步的口径分裂。 */
  const clearDownstream = useCallback(() => {
    setExec(null);
    setExecError("");
    setExecAttempt(0);
    setPolling(false);
    pollTicks.current = 0;
    setNodes([]);
    setRunStage("");
    setVerify(null);
    setReportMd("");
    setReportJson(null);
    // 配方代次变了，覆盖校验结论与说明不足提示一并作废（上一轮的阻断不得残留）
    setCoverageBlock(null);
    setOverrideNoteError("");
  }, []);

  const submitPlan = useCallback(async () => {
    if (!threadId) {
      setError("请先上传并解析一个数据文件。");
      return;
    }
    if (!picked.length) {
      setError("请至少添加一个清洗步骤。");
      return;
    }
    if (derived.pendingIndexes.length) {
      setError(
        `还有 ${derived.pendingIndexes.length} 个步骤待配置（第 ${derived.pendingIndexes
          .map((i) => i + 1)
          .join("、")} 步），补齐必填参数后再生成配方。`,
      );
      return;
    }
    setPlanBusy(true);
    setError("");
    try {
      const operations = picked.map((p) => ({ op: p.op, params: p.params }));
      const r = await api.plan(threadId, operations);
      planSeq.current += 1; // 新配方 = 新代次
      clearDownstream(); // ② 旧执行结果 / 校验 / 报告全部作废
      setPlan(r);
      setConfirmResult(null);
      setScreen("hitl");
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setPlanBusy(false);
    }
  }, [threadId, picked, derived.pendingIndexes, clearDownstream]);

  /* ---------------- 人工确认 ---------------- */
  const clearOverrideHint = useCallback(() => {
    setOverrideNoteError("");
  }, []);

  /** 把后端 409 COVERAGE_BLOCKED 的 detail 收成前端阻断态；detail.uncovered_high 为空时退回本地 riskGate 明细。 */
  const blockFromDetail = useCallback(
    (detail: unknown, fallbackMessage: string) => {
      const d = (detail ?? {}) as ApiDetail;
      const high = Array.isArray(d.uncovered_high) ? d.uncovered_high : [];
      setCoverageBlock({
        message: typeof d.message === "string" && d.message ? d.message : fallbackMessage,
        uncoveredHigh: high.length
          ? high
          : riskGate.uncoveredHighIssues.map((h) => ({
              issue_name: h.issue_name,
              label: h.label,
              severity: h.severity,
              affected_rows: h.affected_rows,
              handlers: h.handlers,
              message: h.message,
            })),
      });
    },
    [riskGate.uncoveredHighIssues],
  );

  const decide = useCallback(
    async (
      approve: boolean,
      reason: string,
      override?: { ack: boolean; skipped: string[]; note: string },
    ) => {
      if (!threadId) return;
      /* 缺陷修复①（高危硬阻断）（知情放行出口）：
         无越权确认（override.ack）时本地先拦住并弹出覆盖校验对话框（体验层）；
         带 override 时放行 —— 后端 check_coverage 仍是最终闸门，
         说明不足由后端返回 409 OVERRIDE_NOTE_REQUIRED，前端就地提示。 */
      if (approve && riskGate.blocked && !override?.ack) {
        setInfo("");
        setError("");
        setOverrideNoteError("");
        blockFromDetail(
          null,
          `${riskGate.uncoveredHighCount} 项体检高危问题未被当前配方覆盖（未达标）；` +
            "如需强行放行，请点「我已知情，仍要继续」并填写跳过原因（≥5 字）。",
        );
        return;
      }
      setConfirmBusy(true);
      setError("");
      setOverrideNoteError("");
      try {
        const r = await api.confirm(threadId, approve, reason, override);
        setConfirmResult(r);
        setCoverageBlock(null);
        if (r.confirmed) {
          clearDownstream(); // ② 新一轮确认即新一轮执行，旧结果不得复用到执行 / 报告 / 导出
          setInfo(
            r.override?.ack
              ? `已确认执行（含越权放行 ${r.override.skipped.length} 项，说明已留痕），接着开始清洗。`
              : "已确认执行，接着开始清洗。",
          );
          setScreen("execute");
        } else {
          setInfo("已驳回本次配方，请回到配方屏调整。");
          setScreen("recipe");
        }
      } catch (e) {
        /* 错误分流按 detail.code（禁止按文案匹配） */
        if (e instanceof ApiError && e.code === "COVERAGE_BLOCKED") {
          blockFromDetail(e.detail, messageOf(e));
        } else if (e instanceof ApiError && e.code === "OVERRIDE_NOTE_REQUIRED") {
          blockFromDetail(e.detail, messageOf(e));
          setOverrideNoteError("请填写跳过原因（≥5 字），不得空放行。");
        } else {
          setError(messageOf(e));
        }
      } finally {
        setConfirmBusy(false);
      }
    },
    [threadId, riskGate.blocked, riskGate.uncoveredHighCount, clearDownstream, blockFromDetail],
  );

  /* ---------------- 执行 ---------------- */
  const refreshRun = useCallback(async () => {
    if (!threadId) return;
    try {
      const r = await api.runStatus(threadId);
      setNodes(r.nodes ?? []);
      setRunStage(r.stage ?? "");
    } catch {
      /* 进度查询失败不阻断主流程，下次轮询再试 */
    }
  }, [threadId]);

  /** 发起执行（幂等：同一配方代次已成功则不重复提交）。屏 5 在挂载时调用一次。
   *  重入时不清结果、只清可能残留的失败横幅，避免「已成功」与「执行失败」同时出现。
   *  缺陷修复②：只有「结果所属代次 == 当前配方代次」才视为新鲜，否则视为过期结果并重跑，
   *  杜绝新配方沿用上一轮回执（执行屏 1 步 / 报告 1 行 / 导出 1 步的口径分裂根因）。 */
  const startExecute = useCallback(async () => {
    if (!threadId) return;
    if (execInFlight.current) return; // 同步判重：在途请求不重复提交
    if (exec && execSeq.current === planSeq.current) {
      setExecError(""); // 已有同一配方代次的结果：横幅属上一次的残留误报，就地清除
      return;
    }
    execInFlight.current = true;
    setExecBusy(true);
    setExecError("");
    setError("");
    setExecAttempt((n) => n + 1);
    pollTicks.current = 0;
    setPolling(true);
    void refreshRun();
    try {
      const r = await api.execute(threadId);
      execSeq.current = planSeq.current; // 记录该结果对应的配方代次
      setExec(r);
      setExecError(""); // 成功即收掉失败横幅，横幅只服务「尚无结果」场景
      appendHistory({
        thread_id: threadId,
        file_name: fileName || "未命名",
        row_count: rowCount,
        col_count: colCount,
        created_at: clockNow(),
        completed: true,
      });
      await refreshRun();
    } catch (e) {
      setExecError(messageOf(e));
      setPolling(false);
    } finally {
      execInFlight.current = false;
      setExecBusy(false);
    }
  }, [threadId, exec, refreshRun, fileName, rowCount, colCount]);

  /* 执行期轮询：1.5s 一次；节点全部终态、或执行结束后轮询尾巴走完即停。
     轮询绑定在会话层（不在屏幕组件里），离开屏 5 也不会漏掉状态更新。 */
  useEffect(() => {
    if (!polling || !threadId) return;
    const allTerminal =
      nodes.length > 0 && nodes.every((n) => n.status === "COMPLETED" || n.status === "FAILED");
    if (allTerminal || (!execBusy && exec && pollTicks.current >= 8)) {
      setPolling(false);
      return;
    }
    const id = window.setInterval(() => {
      pollTicks.current += 1;
      void refreshRun();
    }, 1500);
    return () => window.clearInterval(id);
  }, [polling, threadId, nodes, execBusy, exec, refreshRun]);

  /** 屏 5 的「下一步：校验与报告」门控：执行已返回结果才放行。 */
  const canViewReport = Boolean(exec);

  /** 洗后总行数（洗后比例指标的分母，与对账脚本同口径）。
   *  取序：校验指标 metrics.rows.after → 执行结果行数 → 洗前行数（尚未清洗时的兜底）。 */
  const rowsAfter = useMemo(() => {
    const m = verify?.metrics?.rows as { after?: unknown } | undefined;
    const n = Number(m?.after);
    if (Number.isFinite(n) && n > 0) return n;
    if (exec) return exec.rows.length;
    return rowCount;
  }, [verify, exec, rowCount]);

  /* ---------------- 校验 / 报告 ---------------- */
  const loadVerify = useCallback(async () => {
    if (!threadId) return;
    setReportBusy(true);
    setError("");
    try {
      const r = await api.verify(threadId);
      setVerify(r);
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setReportBusy(false);
    }
  }, [threadId]);

  /** 取报告：返回本次拿到的内容（md 为字符串），调用方可直接落本地文件。 */
  const loadReport = useCallback(
    async (format: "json" | "md"): Promise<unknown> => {
      if (!threadId) return null;
      setReportBusy(true);
      setError("");
      try {
        const r = await api.report(threadId, format);
        void refreshRun();
        if (format === "md") {
          const text = String(r.content ?? "");
          setReportMd(text);
          return text;
        }
        setReportJson(r.content);
        return r.content;
      } catch (e) {
        setError(messageOf(e));
        return null;
      } finally {
        setReportBusy(false);
      }
    },
    [threadId, refreshRun],
  );

  /* ---------------- 导出 ---------------- */
  const doExport = useCallback(
    async (
      format: string,
      opts?: { outDir?: string; attachments?: boolean; busyKey?: string },
    ) => {
      if (!threadId) return;
      const busyKey = opts?.busyKey ?? format;
      setExportBusy(busyKey);
      setError("");
      try {
        const res = (await api.export(threadId, format, opts?.outDir ?? "")) as {
          path: string;
          files?: string[];
        };
        const files = res.files ?? [res.path];
        const extra = files.filter((f) => f !== res.path);
        setExports((prev) => [
          ...prev,
          {
            format,
            path: res.path,
            extra: opts?.attachments ? extra : [],
            at: new Date().toISOString(),
          },
        ]);
        setInfo(`已导出 ${format.toUpperCase()}：${res.path}`);
      } catch (e) {
        setError(messageOf(e));
      } finally {
        setExportBusy("");
      }
    },
    [threadId],
  );

  /* ---------------- 复位 ---------------- */
  const reset = useCallback(() => {
    setScreen("upload");
    setFileName("");
    setFileSize(0);
    setThreadId("");
    setColumns([]);
    setRowCount(0);
    setColCount(0);
    setParsingReport(null);
    setEda(null);
    setPicked([]);
    setPlan(null);
    setConfirmResult(null);
    setExec(null);
    setVerify(null);
    setReportMd("");
    setReportJson(null);
    setExports([]);
    setError("");
    setInfo("");
    setNodes([]);
    setRunStage("");
    setExecBusy(false);
    setExecError("");
    setExecAttempt(0);
    setPolling(false);
    pollTicks.current = 0;
    setCoverageBlock(null); // 新会话不得残留上一轮的覆盖校验阻断
    setOverrideNoteError("");
    planSeq.current = 0; // ② 新会话：配方代次与已执行代次一并复位
    execSeq.current = -1;
  }, []);

  return {
    screen,
    goTo,
    reachable,
    health,
    healthError,
    fileName,
    fileSize,
    threadId,
    columns,
    rowCount,
    colCount,
    parsingReport,
    parseBusy,
    parse,
    eda,
    edaBusy,
    runEda,
    picked,
    derived,
    riskGate,
    addOp,
    updateParam,
    removeOp,
    moveOp,
    resetOps,
    plan,
    planBusy,
    submitPlan,
    confirmResult,
    confirmBusy,
    coverageBlock,
    overrideNoteError,
    clearOverrideHint,
    decide,
    exec,
    execBusy,
    execError,
    execAttempt,
    polling,
    canViewReport,
    nodes,
    runStage,
    startExecute,
    refreshRun,
    verify,
    rowsAfter,
    reportMd,
    reportJson,
    reportBusy,
    loadVerify,
    loadReport,
    exports,
    exportBusy,
    doExport,
    error,
    info,
    setError,
    setInfo,
    reset,
  };
}
