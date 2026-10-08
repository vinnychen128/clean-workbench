// SPDX-License-Identifier: Apache-2.0
/** 屏 7「清洗报告」：一键结论「是否可交付」置顶 + 三段式（体检结论 / 执行过程 /
 *  质量对比）+ 未处理项常驻，并提供 Markdown 原始视图与本地下载；不下结论、不隐藏未达标项。
 *
 *  实现说明：
 * -：首屏**并列**显示「体检结论」+「质量校验结论」，未达标时给出「未达标 N 项」（可点击跳到明细），
 *    未达标区常驻展开、无折叠控件；「全部达标，可交付」只在 passed 且未达标为 0 时出现；
 * -：执行过程每步目标列取 `transform_log[i].target`（无列参数＝「全表」）；
 * -：越权放行留痕（`3_quality.overrides[]`）如实展示，未处理项标「经用户确认未处理」；
 * -：比例键按「百分数 + 1 位小数」显示（KpiCompareTable），分数同样按百分数显示；
 * -：「三、质量对比」表抽为真实组件 `components/KpiCompareTable.tsx`，行为等价。
 */
import React, { useEffect, useMemo, useState } from "react";
import { WizardFooter } from "../components/AppShell";
import {
  Badge,
  Button,
  EmptyState,
  SEVERITY_LABEL,
  SkeletonBlock,
  downloadJson,
  downloadText,
  fmtNum,
  severityBadge,
  useProgressive,
} from "../components/ui/primitives";
import { InfoBanner, InlineError, InlineProgress, MiniBar } from "../components/ui/feedback";
import { AiReportSummary } from "../components/AiReportSummary";
import { KpiCompareTable } from "../components/KpiCompareTable";
import { DETECTORS, opLabel } from "../lib/ops";
import { fmtPct, uiText, unmetMessageText } from "../lib/format";
import { MetricValue, UnmetItem, normalizeUnmet } from "../api";
import { Session } from "../hooks/useSession";

type RepMetric = MetricValue;

interface RepIssue {
  issue_name: string;
  column?: string | null;
  severity?: string;
  rows?: number[];
}

interface RepUnhandled {
  issue_name: string;
  column?: string | null;
  severity?: string;
  affected_rows?: number;
  reason?: string;
  /** 越权放行的项在此为 true，reason 里含「经用户确认未处理」 */
  user_acknowledged?: boolean;
}

interface RepLog {
  step?: number;
  op?: string;
  /** 该步作用对象（列名，多列顿号分隔；无列参数＝「全表」） */
  target?: string;
  column?: string | null;
  rows_affected?: number;
  skipped?: boolean;
  skip_reason?: string;
}

/** 越权放行留痕（仅越权时出现）。 */
interface RepOverride {
  ack?: boolean;
  skipped?: string[];
  note?: string;
  at?: string;
}

interface RepContent {
  thread_id?: string;
  source?: { file_name?: string };
  unhandled?: RepUnhandled[];
  sections?: {
    "1_profile"?: {
      title?: string;
      severity_summary?: Record<string, number>;
      issues?: RepIssue[];
      conclusion?: string;
    };
    "2_process"?: { recipe_id?: string; transform_log?: RepLog[] };
    "3_quality"?: {
      metrics?: Record<string, RepMetric>;
      passed?: boolean;
      /** 对象数组（旧字符串形态由 normalizeUnmet 兜底） */
      unmet?: unknown;
      /** 质量校验结论 */
      conclusion?: string;
      /** 越权放行留痕，无越权时该键不存在 */
      overrides?: RepOverride[];
    };
    "4_unhandled"?: { count?: number; unhandled?: RepUnhandled[]; conclusion?: string };
  };
}

function detectorName(key: string): string {
  return DETECTORS[key]?.name ?? key;
}

/** 每步目标列 —— target 优先，历史 column 兜底，都没有＝「全表」。 */
function stepTarget(l: RepLog): string {
  const t = (l.target ?? "").trim();
  if (t) return t;
  const c = (l.column ?? "").trim();
  return c || "全表";
}

export function ReportScreen({ s }: { s: Session }) {
  const [tab, setTab] = useState<"structured" | "md">("structured");

  /* 进屏补齐校验与报告 JSON（幂等：已有数据不重复拉取）。
     缺陷修复②：必须「先校验、后取报告」串行——原先两者并发发起，报告可能先于校验
     生成，其「三、质量对比」段在无指标时被写入并被后端缓存，导致该项恒显「暂无前后对比指标」。 */
  useEffect(() => {
    if (!s.exec) return;
    let alive = true;
    void (async () => {
      if (!s.verify) await s.loadVerify();
      if (alive && !s.reportJson) await s.loadReport("json");
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.exec]);

  const content = (s.reportJson ?? null) as RepContent | null;
  const sec = content?.sections ?? {};
  const profileSec = sec["1_profile"] ?? {};
  const processSec = sec["2_process"] ?? {};
  const qualitySec = sec["3_quality"] ?? {};
  const unhandledSec = sec["4_unhandled"] ?? {};

  /* 缺陷修复②：「三、质量对比」优先用报告内指标；报告缺指标（历史缓存 / 旧数据）时
     回退到本次校验结果，避免空对象被 ?? 视为有效值而恒显「暂无前后对比指标」。 */
  const reportQuality = qualitySec.metrics ?? {};
  const reportHasQuality = Object.keys(reportQuality).length > 0;
  const metrics = useMemo<Record<string, RepMetric>>(
    () => (reportHasQuality ? reportQuality : ((s.verify?.metrics as Record<string, RepMetric>) ?? {})),
    [reportQuality, reportHasQuality, s.verify],
  );
  const summary = profileSec.severity_summary ?? {};
  const issues = profileSec.issues ?? [];
  const logs = processSec.transform_log ?? [];
  const unhandled = unhandledSec.unhandled ?? content?.unhandled ?? [];
  const passed = reportHasQuality ? Boolean(qualitySec.passed) : Boolean(s.verify?.passed ?? qualitySec.passed);
  /* unmet 为对象数组（含 message）；旧字符串形态就地归一，不让界面出现两种形态。 */
  const unmet = useMemo<UnmetItem[]>(
    () => normalizeUnmet(reportHasQuality ? qualitySec.unmet : (s.verify?.unmet ?? qualitySec.unmet)),
    [reportHasQuality, qualitySec.unmet, s.verify],
  );
  /* 仅越权放行时后端才给 overrides[]，无越权时这里为空数组（不渲染该区块）。 */
  const overrides = (qualitySec.overrides ?? []).filter((o) => o && o.ack);
  /* 质量校验结论 —— 后端 conclusion 优先，缺省时按 passed/未达标数现场拼（口径一致）。 */
  const qualityConclusion = unmetMessageText(
    qualitySec.conclusion ??
      s.verify?.conclusion ??
      (passed ? "通过 · 可交付（未达标 0 项）" : `未达标 ${unmet.length} 项`),
  );
  const profileConclusion = unmetMessageText(profileSec.conclusion ?? "—");
  /** 「全部达标，可交付」只在 passed 且未达标为 0 时出现。 */
  const allClear = passed && unmet.length === 0;
  const tid = content?.thread_id ?? "";
  const tid8 = tid.replace(/[^a-zA-Z0-9]/g, "").slice(-8) || "current";

  const logPage = useProgressive(logs, 50, 100);
  const unhandledPage = useProgressive(unhandled, 50, 100);
  /** 未处理项里被越权放行的条数（首屏如实计数）。 */
  const ackedCount = unhandled.filter((u) => u.user_acknowledged).length;

  async function onDownloadMd() {
    const md = s.reportMd || ((await s.loadReport("md")) as string) || "";
    if (!md) return;
    downloadText(`清洗报告_${tid8}.md`, md, "text/markdown;charset=utf-8");
  }

  async function onDownloadJson() {
    const data = s.reportJson ?? (await s.loadReport("json"));
    if (!data) return;
    downloadJson(`清洗报告_${tid8}.json`, data);
  }

  const jumpToUnmet = () => {
    const el = document.getElementById("quality-unmet");
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  return (
    <>
      <div className="screen screen--max">
        <div className="screen-head">
          <h2 className="screen-q">第七步：清洗报告</h2>
          <p className="screen-sub">
            结论只依据真实体检与前后校验结果：未达标项、未处理项一律如实列出，不做美化。
          </p>
        </div>

        {!s.exec && (
          <section className="panel">
            <EmptyState
              icon="▤"
              title="还没有可出的报告"
              desc="报告基于已完成的清洗生成，请先回到执行进度屏完成一次清洗。"
              action={
                <Button variant="primary" onClick={() => s.goTo("execute")}>
                  回执行屏
                </Button>
              }
            />
          </section>
        )}

        {s.exec && (
          <>
            {/* 报告屏顶部「人话摘要」（只读、默认折叠、点开才请求；未启用不渲染） */}
            <AiReportSummary threadId={tid} />

            <section className="panel">
              <div className="toolbar" style={{ marginBottom: 0 }}>
                <div className="verdict">
                  <Badge tone={passed ? "success" : "danger"}>{passed ? "通过 · 可交付" : "未通过 · 需复核"}</Badge>
                  {/* 首屏并列「体检结论」+「质量校验结论」，不再只给一个判定字 */}
                  <span className="muted">体检结论：{profileConclusion}</span>
                  <span className="muted">质量校验结论：{qualityConclusion}</span>
                  {unmet.length > 0 && (
                    <Button size="sm" variant="danger" onClick={jumpToUnmet}>
                      未达标 {unmet.length} 项 · 查看明细
                    </Button>
                  )}
                  {ackedCount > 0 && (
                    <Badge tone="warning">含 {ackedCount} 项经用户确认未处理</Badge>
                  )}
                  <span className="muted">
                    {content?.source?.file_name ?? "—"} · 会话 {tid8 ? `…${tid8}` : "—"}
                  </span>
                </div>
                <span className="impact-bar__spacer" />
                <div className="seg" role="tablist" aria-label="报告视图">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={tab === "structured"}
                    className={`seg__btn${tab === "structured" ? " is-active" : ""}`}
                    onClick={() => setTab("structured")}
                  >
                    结构化
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={tab === "md"}
                    className={`seg__btn${tab === "md" ? " is-active" : ""}`}
                    onClick={() => setTab("md")}
                  >
                    Markdown 原文
                  </button>
                </div>
                <Button variant="secondary" loading={s.reportBusy} onClick={() => void onDownloadMd()}>
                  下载 Markdown
                </Button>
                <Button variant="ghost" onClick={() => void onDownloadJson()}>
                  下载 JSON
                </Button>
              </div>

              {/* 未达标区默认展开、无折叠控件（常驻区块，DevTools 查无 toggle） */}
              {unmet.length > 0 && (
                <div className="unmet" id="quality-unmet">
                  <div className="unmet__title">
                    前后校验未达标 {unmet.length} 项（分母 = 洗后总行数 {fmtNum(s.rowsAfter)} 行）
                  </div>
                  <ul>
                    {unmet.map((u, i) => (
                      <li key={`${u.key}-${i}`}>{unmetMessageText(u.message)}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* 越权放行留痕 —— 跳过项 + 说明 + 时间；无越权时不渲染本区块 */}
              {overrides.length > 0 && (
                <div className="unmet" style={{ borderColor: "var(--warning-500)", background: "var(--warning-100)" }}>
                  <div className="unmet__title">知情放行留痕（{overrides.length} 条）</div>
                  <ul>
                    {overrides.map((o, i) => (
                      <li key={`ov-${i}`}>
                        跳过 {o.skipped?.length ?? 0} 项
                        {o.skipped && o.skipped.length > 0 ? `（${o.skipped.map(detectorName).join("、")}）` : ""}：说明「
                        {o.note || "未填写"}」· {o.at ?? "时间未记录"}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>

            {!content && !s.verify && (
              <section className="panel">
                {/* 各阶段都有明确加载态（禁止白屏）：报告未取回时给进度 + 骨架屏 */}
                <InlineProgress label={s.reportBusy ? "正在生成报告与前后校验指标…" : "正在取回报告数据…"} />
                <SkeletonBlock rows={4} />
              </section>
            )}
            {s.error && <InlineError>{s.error}</InlineError>}

            {tab === "md" && (
              <section className="panel">
                <div className="panel__head">
                  <span className="panel__title">Markdown 原文</span>
                  <span className="panel__meta">{s.reportMd ? `${s.reportMd.length} 字符` : "尚未生成"}</span>
                </div>
                {s.reportMd ? (
                  <pre className="md-view">{s.reportMd}</pre>
                ) : (
                  <EmptyState
                    icon="✎"
                    title="尚未取回 Markdown"
                    desc="报告原文按需生成，点下方按钮取回后可阅读与下载。"
                    action={
                      <Button variant="secondary" loading={s.reportBusy} onClick={() => void onDownloadMd()}>
                        生成并下载 Markdown
                      </Button>
                    }
                  />
                )}
              </section>
            )}

            {tab === "structured" && (content || s.verify) && (
              <div className="report-grid">
                <section className="report-card">
                  <h3 className="report-card__title">一、体检结论</h3>
                  <div className="severity-grid">
                    <div className="severity-cell">
                      <span className="severity-cell__num severity-cell__num--danger">
                        {fmtNum(summary.high ?? 0)}
                      </span>
                      <span className="severity-cell__label">高危</span>
                    </div>
                    <div className="severity-cell">
                      <span className="severity-cell__num severity-cell__num--warning">
                        {fmtNum(summary.medium ?? 0)}
                      </span>
                      <span className="severity-cell__label">中危</span>
                    </div>
                    <div className="severity-cell">
                      <span className="severity-cell__num severity-cell__num--info">
                        {fmtNum(summary.low ?? 0)}
                      </span>
                      <span className="severity-cell__label">低危</span>
                    </div>
                  </div>
                  <p className="report-card__lead">体检结论：{profileConclusion}</p>
                  {issues.length > 0 ? (
                    <div className="report-issues">
                      {issues.map((it, i) => {
                        const score = Number(
                          (it as unknown as Record<string, unknown>)[`${it.issue_name}_score`] ?? NaN,
                        );
                        return (
                          <div className="report-issue" key={`${it.issue_name}-${i}`}>
                            <Badge tone={severityBadge(it.severity ?? "")}>
                              {SEVERITY_LABEL[it.severity ?? ""] ?? "—"}
                            </Badge>
                            <span>{detectorName(it.issue_name)}</span>
                            {it.column && <span className="mono muted">{it.column}</span>}
                            {Number.isFinite(score) && (
                              <>
                                <MiniBar
                                  value={score}
                                  max={1}
                                  tone={it.severity === "high" ? "danger" : it.severity === "medium" ? "warning" : "primary"}
                                />
                                {/* 分数是 0~1 比例，按百分数 + 1 位小数显示，不出现无单位裸小数 */}
                                <span className="muted num">{fmtPct(score)}</span>
                              </>
                            )}
                            <span className="muted">涉及 {(it.rows ?? []).length} 行</span>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="muted">本次未检出问题项。</p>
                  )}
                </section>

                <section className="report-card" id="quality-compare">
                  <h3 className="report-card__title">三、质量对比</h3>
                  {Object.keys(metrics).length === 0 ? (
                    <p className="muted">暂无前后对比指标。</p>
                  ) : (
                    <KpiCompareTable metrics={metrics} />
                  )}
                  {allClear ? (
                    <p className="passed-note">{qualityConclusion}</p>
                  ) : (
                    unmet.length > 0 && (
                      <div className="unmet">
                        <div className="unmet__title">未达标 {unmet.length} 项</div>
                        <ul>
                          {unmet.map((u, i) => (
                            <li key={`card-${u.key}-${i}`}>{unmetMessageText(u.message)}</li>
                          ))}
                        </ul>
                      </div>
                    )
                  )}
                </section>

                <section className="report-card report-card--wide">
                  <h3 className="report-card__title">二、执行过程</h3>
                  {logs.length === 0 ? (
                    <p className="muted">本次执行没有可展示的操作步骤记录。</p>
                  ) : (
                    <table className="table table--numeric">
                      <thead>
                        <tr>
                          <th>步骤</th>
                          <th>操作</th>
                          <th>目标列</th>
                          <th className="num">影响行数</th>
                          <th>说明</th>
                        </tr>
                      </thead>
                      <tbody>
                        {logPage.shown.map((l, i) => (
                          <tr key={`${l.step}-${i}`}>
                            <td className="num">第 {l.step ?? i + 1} 步</td>
                            <td>{opLabel(l.op ?? "")}</td>
                            {/* 目标列取后端 transform_log[i].target（无列参数＝「全表」） */}
                            <td className="mono">{stepTarget(l)}</td>
                            <td className="num">{fmtNum(l.rows_affected ?? 0)}</td>
                            <td>
                              {l.skipped ? (
                                <Badge tone="warning">已跳过 · {l.skip_reason || "原因未记录"}</Badge>
                              ) : (
                                <Badge tone="success">已执行</Badge>
                              )}
                            </td>
                          </tr>
                        ))}
                        {logPage.hasMore && (
                          <tr>
                            <td colSpan={5}>
                              <div className="toolbar" style={{ marginBottom: 0 }}>
                                <Button size="sm" variant="secondary" onClick={logPage.expand}>
                                  {logPage.moreLabel}
                                </Button>
                                <Button size="sm" variant="ghost" onClick={logPage.expandAll}>
                                  显示全部
                                </Button>
                                <span className="muted">{logPage.hint}</span>
                              </div>
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  )}
                  {processSec.recipe_id && (
                    <p className="muted" style={{ marginTop: "var(--space-3)" }}>
                      配方：<span className="mono">{processSec.recipe_id}</span>
                    </p>
                  )}
                </section>

                <section className="report-card report-card--wide">
                  <h3 className="report-card__title">
                    四、未处理项{unhandled.length > 0 ? `（${unhandled.length}）` : ""}
                  </h3>
                  <InfoBanner>
                    以下内容未被子配方覆盖或未识别，报告如实列出，不会被标记为已清洗；
                    经你知情放行的项标「经用户确认未处理」，同样不算作已处理。
                  </InfoBanner>
                  {unhandled.length === 0 ? (
                    <p className="passed-note">
                      {unmetMessageText(unhandledSec.conclusion) || "全部检出问题均有配方操作覆盖，无遗留未处理项。"}
                    </p>
                  ) : (
                    <table className="table">
                      <thead>
                        <tr>
                          <th>问题</th>
                          <th>列</th>
                          <th className="num">涉及行数</th>
                          <th>原因</th>
                        </tr>
                      </thead>
                      <tbody>
                        {unhandledPage.shown.map((u, i) => (
                          <tr key={`${u.issue_name}-${i}`}>
                            <td>
                              {detectorName(u.issue_name)}
                              {/* 越权放行的项标「经用户确认未处理」，与"检测器未覆盖"区分 */}
                              {u.user_acknowledged && (
                                <div>
                                  <Badge tone="warning">经用户确认未处理</Badge>
                                </div>
                              )}
                            </td>
                            <td className="mono">{u.column ?? "—"}</td>
                            <td className="num">{fmtNum(u.affected_rows ?? 0)}</td>
                            <td>{unmetMessageText(u.reason ?? "—")}</td>
                          </tr>
                        ))}
                        {unhandledPage.hasMore && (
                          <tr>
                            <td colSpan={4}>
                              <div className="toolbar" style={{ marginBottom: 0 }}>
                                <Button size="sm" variant="secondary" onClick={unhandledPage.expand}>
                                  {unhandledPage.moreLabel}
                                </Button>
                                <Button size="sm" variant="ghost" onClick={unhandledPage.expandAll}>
                                  显示全部
                                </Button>
                                <span className="muted">{unhandledPage.hint}</span>
                              </div>
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  )}
                </section>
              </div>
            )}
          </>
        )}
      </div>

      <WizardFooter
        hint={
          !s.exec
            ? "先完成执行才能出报告"
            : allClear
              ? "前后校验全部达标，可交付"
              : `存在 ${unmet.length} 项未达标 / ${unhandled.length} 项未处理（其中 ${ackedCount} 项经用户确认未处理），请自行复核后再导出`
        }
      >
        <Button variant="secondary" onClick={() => s.goTo("execute")}>
          上一步：执行
        </Button>
        <Button variant="primary" disabled={!s.exec} onClick={() => s.goTo("export")}>
          下一步：导出结果
        </Button>
      </WizardFooter>
    </>
  );
}
