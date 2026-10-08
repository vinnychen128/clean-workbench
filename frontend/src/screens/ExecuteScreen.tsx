// SPDX-License-Identifier: Apache-2.0
/** 屏 5「执行进度」：节点流水线 + 耗时 + 失败突出 + 有限重试 + 1.5s 轮询。
 *  进屏即发起一次 execute（幂等：进行中或已成功不再重复提交，重进本屏不会重复跑）；
 *  轮询挂在 useSession 上，离开本屏再回来仍能看到最新节点状态。 */
import React, { useEffect, useState } from "react";
import { WizardFooter } from "../components/AppShell";
import {
  Badge,
  Button,
  EmptyState,
  SkeletonBlock,
  Tooltip,
  formatClock,
  fmtNum,
  useProgressive,
} from "../components/ui/primitives";
import { InlineError, InlineProgress } from "../components/ui/feedback";
import { opLabel } from "../lib/ops";
import { Session } from "../hooks/useSession";
import type { RunStatusNode, TransformLogEntry } from "../api";

const NODE_LABEL: Record<string, string> = {
  parse: "解析文件",
  eda: "体检扫描",
  plan: "生成配方",
  confirm: "人工确认",
  execute: "执行清洗",
  verify_check: "前后校验",
  report_build: "生成报告",
  export: "导出结果",
};

const STATUS_LABEL: Record<RunStatusNode["status"], string> = {
  PENDING: "待执行",
  RUNNING: "进行中",
  COMPLETED: "已完成",
  FAILED: "失败",
  AWAITING_HITL: "等待确认",
};

/** 失败重试上限（含首次执行共 3 次）。 */
const MAX_ATTEMPT = 3;

function itemClass(status: RunStatusNode["status"]): string {
  if (status === "COMPLETED") return "pipeline__item pipeline__item--done";
  if (status === "FAILED") return "pipeline__item pipeline__item--failed";
  if (status === "RUNNING") return "pipeline__item pipeline__item--running";
  if (status === "AWAITING_HITL") return "pipeline__item pipeline__item--hitl";
  return "pipeline__item";
}

function ms2text(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "0.0s";
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  return `${Math.floor(s / 60)}m ${(s % 60).toFixed(0)}s`;
}

/** 每步作用对象 —— target 优先（无列参数时后端给「全表」），历史 column 兜底。 */
function stepTarget(e: TransformLogEntry): string {
  const t = (e.target ?? "").trim();
  if (t) return t;
  const c = (e.column ?? "").trim();
  return c || "全表";
}

/** 执行过程每步的人话行 —— 「第 N 步 · 算子中文名 · 作用：<target>」。 */
export function stepLine(e: TransformLogEntry, index: number): string {
  const n = e.step ?? index + 1;
  return `第 ${n} 步 · ${opLabel(e.op ?? "")} · 作用：${stepTarget(e)}`;
}

export function ExecuteScreen({ s }: { s: Session }) {
  const [now, setNow] = useState(() => Date.now());

  /* 进屏发起执行（幂等守卫在 useSession.startExecute 内部）。 */
  useEffect(() => {
    void s.startExecute();
    // 仅进屏触发一次：依赖项留空以避免重渲染重复提交
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* 进行中每 500ms 刷新耗时显示（reduced-motion 下同样保留，仅文字更新）。 */
  useEffect(() => {
    if (!s.execBusy && !s.polling) return;
    const id = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(id);
  }, [s.execBusy, s.polling]);

  const nodes = s.nodes;
  const doneCount = nodes.filter((n) => n.status === "COMPLETED").length;
  const failed = nodes.filter((n) => n.status === "FAILED");
  const runningNode = nodes.find((n) => n.status === "RUNNING") ?? null;

  const startMs = nodes
    .filter((n) => n.started_at)
    .map((n) => new Date(n.started_at as string).getTime())
    .filter((n) => Number.isFinite(n));
  const endedMs = nodes
    .filter((n) => n.ended_at)
    .map((n) => new Date(n.ended_at as string).getTime())
    .filter((n) => Number.isFinite(n));
  const allEnded = nodes.length > 0 && nodes.every((n) => !!n.ended_at);
  const elapsed =
    startMs.length > 0
      ? Math.max(0, (allEnded ? Math.max(...endedMs) : now) - Math.min(...startMs))
      : 0;

  const affectedRows = (s.exec?.transform_log ?? []).reduce(
    (sum, e) => sum + (typeof e.rows_affected === "number" ? e.rows_affected : 0),
    0,
  );
  const retryLeft = Math.max(0, MAX_ATTEMPT - s.execAttempt);
  const waiting = !s.exec && !s.execError;
  /* 执行过程每步一行（「第 N 步 · 算子中文名 · 作用：<target>」）；
     长清单按「前 N 条 + 展开更多」渲染，数百步也不卡。 */
  const logPage = useProgressive(s.exec?.transform_log ?? [], 50, 100);

  return (
    <>
      <div className="screen screen--max">
        <div className="screen-head">
          <h2 className="screen-q">第五步：正在清洗</h2>
          <p className="screen-sub">
            节点状态每 1.5 秒刷新一次；切到别的步骤不会中断本次执行，回到本屏仍是实时进度。
          </p>
        </div>

        {waiting && (
          <section className="panel">
            <InlineProgress
              label={
                runningNode
                  ? `正在执行：${NODE_LABEL[runningNode.node_name] ?? runningNode.node_name}`
                  : "正在提交执行请求…"
              }
            />
            <SkeletonBlock rows={3} />
          </section>
        )}

        {/* 失败横幅只在「尚无结果」时展示（缺陷修复）：一旦执行已返回结果，
            此前的网络/500 失败属重复提交带来的噪声，不再与结果表并存，也不再挡住「下一步」。 */}
        {s.execError && !s.exec && (
          <section className="panel">
            <InlineError>{s.execError}</InlineError>
            <p className="muted" style={{ marginTop: "var(--space-3)" }}>
              已尝试 {s.execAttempt} 次。清洗是本地同步调用，失败通常来自本地服务未就绪或数据被占用；
              可点「重试」，若仍失败请回到配方屏检查步骤。
            </p>
            <div className="toolbar" style={{ marginTop: "var(--space-3)", marginBottom: 0 }}>
              <Button
                variant="primary"
                disabled={retryLeft === 0}
                onClick={() => void s.startExecute()}
                title={retryLeft === 0 ? `已重试 ${MAX_ATTEMPT - 1} 次，请检查数据后重来` : undefined}
              >
                {retryLeft === 0 ? "已达重试上限" : `重试（剩 ${retryLeft} 次）`}
              </Button>
              <Button variant="ghost" onClick={() => s.goTo("recipe")}>
                回配方屏检查
              </Button>
            </div>
          </section>
        )}

        <section className="panel">
          <div className="panel__head">
            <span className="panel__title">节点流水线</span>
            <span className="panel__meta">
              已完成 {doneCount}/{nodes.length || 8} · 校验 / 报告节点为「报告阶段补跑」 · 用时 {ms2text(elapsed)}
              {s.polling && " · 轮询中"}
            </span>
          </div>

          {nodes.length === 0 ? (
            <EmptyState icon="⇅" title="还没有节点记录" desc="执行请求提交后，这里会逐节点显示状态与耗时。" />
          ) : (
            <div className="pipeline">
              {nodes.map((n, i) => {
                const label = NODE_LABEL[n.node_name] ?? n.node_name;
                const note =
                  n.status === "PENDING" && (n.node_name === "verify_check" || n.node_name === "report_build")
                    ? "报告阶段补跑（进入报告屏时自动执行）"
                    : undefined;
                return (
                  <div className={itemClass(n.status)} key={`${n.node_name}-${i}`}>
                    <div className="pipeline__rail">
                      <span className="pipeline__dot" aria-hidden>
                        {n.status === "COMPLETED" ? "✓" : n.status === "FAILED" ? "!" : i + 1}
                      </span>
                      {i < nodes.length - 1 && <span className="pipeline__connector" aria-hidden />}
                    </div>
                    <div className="pipeline__body">
                      <div className="pipeline__head">
                        <span className="pipeline__label">{label}</span>
                        <Badge
                          tone={
                            n.status === "COMPLETED"
                              ? "success"
                              : n.status === "FAILED"
                                ? "danger"
                                : n.status === "RUNNING"
                                  ? "primary"
                                  : n.status === "AWAITING_HITL"
                                    ? "warning"
                                    : "neutral"
                          }
                        >
                          {STATUS_LABEL[n.status]}
                        </Badge>
                        <span className="pipeline__time">
                          {formatClock(n.started_at)} → {formatClock(n.ended_at)}
                          {n.attempt > 1 && ` · 第 ${n.attempt} 次`}
                        </span>
                      </div>
                      {note && <div className="pipeline__note">{note}</div>}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {failed.length > 0 && (
          <section className="panel">
            <InlineError>
              节点「{NODE_LABEL[failed[0].node_name] ?? failed[0].node_name}」执行失败
              {failed.length > 1 ? `（共 ${failed.length} 个失败节点）` : ""}。
            </InlineError>
          </section>
        )}

        {s.exec && failed.length === 0 && (
          <section className="panel">
            <div className="panel__head">
              <span className="panel__title">执行结果</span>
              <span className="panel__meta">用时 {ms2text(elapsed)}</span>
            </div>
            <table className="table table--numeric">
              <tbody>
                <tr>
                  <td>输出规模</td>
                  <td className="num">
                    {fmtNum(s.exec.rows.length)} 行 × {s.exec.columns.length} 列
                  </td>
                </tr>
                <tr>
                  <td>清洗步骤</td>
                  <td className="num">{s.exec.transform_log.length} 步</td>
                </tr>
                <tr>
                  <td>累计影响行数</td>
                  <td className="num">{fmtNum(affectedRows)}</td>
                </tr>
                <tr>
                  <td>结果引用</td>
                  <td className="num mono">{s.exec.data_ref}</td>
                </tr>
              </tbody>
            </table>
            <p className="muted" style={{ marginTop: "var(--space-3)" }}>
              状态为「待执行」的校验 / 报告节点为「报告阶段补跑」——进入报告屏时自动执行，
              不计入本屏进度，属于设计内行为。
            </p>

            {/* 执行过程逐条列出「改了什么（作用在哪一列）」，与报告「二、执行过程」同源 */}
            {s.exec.transform_log.length > 0 && (
              <>
                <div className="issue-group-title" style={{ marginTop: "var(--space-4)" }}>
                  执行过程（{s.exec.transform_log.length} 步）
                </div>
                <div className="recipe-steps recipe-steps--compact">
                  {logPage.shown.map((e, i) => (
                    <div className="recipe-step" key={`${e.step}-${i}`}>
                      <span className="recipe-step__idx">{e.step ?? i + 1}</span>
                      <span className="recipe-step__text">
                        {stepLine(e, i)}
                        {e.skipped && <Badge tone="warning">已跳过 · {e.skip_reason || "原因未记录"}</Badge>}
                      </span>
                    </div>
                  ))}
                  {logPage.hasMore && (
                    <div className="toolbar" style={{ marginBottom: 0 }}>
                      <Button size="sm" variant="secondary" onClick={logPage.expand}>
                        {logPage.moreLabel}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={logPage.expandAll}>
                        显示全部
                      </Button>
                      <span className="muted">{logPage.hint}</span>
                    </div>
                  )}
                </div>
              </>
            )}
          </section>
        )}

        {!s.exec && !waiting && !s.execError && (
          <section className="panel">
            <EmptyState icon="⇅" title="本会话尚无执行结果" desc="回到确认屏重新确认配方后再执行。" />
          </section>
        )}
      </div>

      <WizardFooter
        hint={
          s.execBusy
            ? "清洗进行中，请稍候"
            : s.execError && !s.exec
              ? "执行未完成，先重试或回配方屏检查"
              : s.canViewReport
                ? `执行完成，影响 ${fmtNum(affectedRows)} 行`
                : "执行完成后可查看报告"
        }
      >
        <Button variant="secondary" onClick={() => s.goTo("hitl")}>
          上一步：确认
        </Button>
        {s.canViewReport ? (
          <Button variant="primary" onClick={() => s.goTo("report")}>
            下一步：查看报告
          </Button>
        ) : (
          <Tooltip text="需先执行成功（无失败节点）才能查看报告">
            <span>
              <Button variant="primary" disabled>
                下一步：查看报告
              </Button>
            </span>
          </Tooltip>
        )}
      </WizardFooter>
    </>
  );
}
