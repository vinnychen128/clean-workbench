// SPDX-License-Identifier: Apache-2.0
/** 屏 2「体检」：单一问题 = 数据有哪些毛病。
 *  顶部 KpiStrip 给出问题规模 KPI（类型数 / 高 / 中 / 低 / 波及行数 + 检测器异常），
 *  不再只有一张表；每个问题可一键转为建议清洗步骤。
 *
 *  实现说明：
 * -：问题表抽为真实组件 `components/IssueTable.tsx`（行为等价、视觉不变）；
 * -：点问题行打开行详情抽屉，样本值取后端 `profile.issues[i].samples`（脱敏、只读），
 *    前端**不**按行号回索引原始数据（列被清洗后行号会错位）；
 * -：加入建议步骤时按问题命中的列预填目标列，无法唯一确定列时不猜并给提示；
 * -：占比统一「百分数 + 1 位小数」，分母 = 本次扫描总行数（洗前数据规模）。
 */
import React, { useMemo, useState } from "react";
import { WizardFooter } from "../components/AppShell";
import {
  Button,
  Collapse,
  EmptyState,
  SkeletonBlock,
  fmtNum,
} from "../components/ui/primitives";
import { KpiStrip } from "../components/ui/feedback";
import { AiColumnAdvice } from "../components/AiColumnAdvice";
import { IssueTable } from "../components/IssueTable";
import { IssueDetailDrawer } from "../components/IssueDetailDrawer";
import { ProfileIssue } from "../api";
import { DETECTORS, prefillForIssue, specOf } from "../lib/ops";
import { pctOf } from "../lib/format";
import { Session } from "../hooks/useSession";

/** 问题命中的列（后端 profile.issues[i].columns / column；预填用）。 */
function issueColumns(it: ProfileIssue): string[] {
  if (it.columns && it.columns.length > 0) return it.columns;
  if (it.column) return [it.column];
  return [];
}

/** 问题级建议（可选，后端 issue 上的扩展键）：suggest_op / suggest_params。
 *  用于补全「检测器 → 算子**参数**」链路（如数量列 3件 → 单位剥离：to=纯数值）。
 *  仅在后端给出且算子确实在目录中时采纳，否则一律回落到 DETECTORS 的 defaultOp。 */
function issueSuggestion(
  it: ProfileIssue,
  fallbackOp: string,
): { op: string; extra: Record<string, unknown> } {
  const rawOp = it.suggest_op;
  const op = typeof rawOp === "string" && rawOp && specOf(rawOp) ? rawOp : fallbackOp;
  const rawParams = it.suggest_params;
  const extra =
    rawParams && typeof rawParams === "object" && !Array.isArray(rawParams)
      ? (rawParams as Record<string, unknown>)
      : {};
  return { op, extra };
}

export function EdaScreen({ s }: { s: Session }) {
  const issues = s.eda?.profile.issues ?? [];
  const detectorErrors = s.eda?.profile.detector_errors ?? [];
  /** 当前打开的问题（null = 抽屉关闭） */
  const [detail, setDetail] = useState<ProfileIssue | null>(null);

  const stats = useMemo(() => {
    const count = (sev: string) => issues.filter((i) => i.severity === sev).length;
    const touched = new Set<number>();
    issues.forEach((i) => (i.rows ?? []).forEach((r) => touched.add(r)));
    const worst: "danger" | "warning" | "success" =
      count("high") > 0 ? "danger" : issues.length ? "warning" : "success";
    return { high: count("high"), medium: count("medium"), low: count("low"), touched: touched.size, worst };
  }, [issues]);

  /** 加入建议步骤 —— 能唯一确定列就预填目标列，否则不猜并给一句可操作提示。 */
  const addSuggested = (it: ProfileIssue) => {
    const spec = DETECTORS[it.issue_name];
    if (!spec) return;
    const { op, extra } = issueSuggestion(it, spec.defaultOp);
    const { params, note } = prefillForIssue(op, issueColumns(it));
    s.addOp(op, { ...params, ...extra });
    s.setInfo(
      `已把「${spec.name}」的建议步骤（${op}）加入配方` +
        `${note ? `；${note}` : "，目标列已按体检命中列预填"}` +
        `${Object.keys(extra).length > 0 ? "，参数已按体检建议预填" : ""}，可在配方屏调整参数。`,
    );
    setDetail(null);
  };

  const addAllSuggested = () => {
    const seen = new Set<string>();
    issues.forEach((it) => {
      const spec = DETECTORS[it.issue_name];
      if (!spec || seen.has(it.issue_name)) return;
      seen.add(it.issue_name);
      const { op, extra } = issueSuggestion(it, spec.defaultOp);
      const { params } = prefillForIssue(op, issueColumns(it));
      s.addOp(op, { ...params, ...extra });
    });
    s.setInfo(`已按体检结果加入 ${seen.size} 个建议步骤（能确定列的目标列已预填），请到配方屏确认顺序与参数。`);
  };

  if (!s.eda) {
    return (
      <>
        <div className="screen screen--max">
          <div className="screen-head">
            <h2 className="screen-q">第二步：先体检，再决定怎么洗</h2>
            <p className="screen-sub">9 类检测器只读扫描，不会改动你的数据。</p>
          </div>
          <section className="panel">
            {s.edaBusy ? (
              <SkeletonBlock rows={5} />
            ) : (
              <EmptyState
                icon="◔"
                title="还没有体检结果"
                desc="对已解析的数据跑一次全量体检，得到问题清单与建议清洗步骤。"
                action={
                  <Button variant="primary" disabled={!s.threadId} onClick={() => void s.runEda()}>
                    运行体检
                  </Button>
                }
              />
            )}
          </section>
        </div>
        <WizardFooter hint="体检只读，不会改动数据">
          <Button variant="secondary" onClick={() => s.goTo("upload")}>上一步：上传</Button>
          <Button variant="primary" disabled>下一步：编写配方</Button>
        </WizardFooter>
      </>
    );
  }

  /* 体检阶段占比分母 = 本次扫描总行数（洗前规模）；洗后比例另用 session.rowsAfter。 */
  const ratio = pctOf(stats.touched, s.rowCount) ?? "—";

  return (
    <>
      <div className="screen screen--max">
        <div className="screen-head">
          <h2 className="screen-q">第二步：先体检，再决定怎么洗</h2>
          <p className="screen-sub">
            共 {issues.length} 类问题，波及 {fmtNum(stats.touched)} 行（占本次扫描 {fmtNum(s.rowCount)} 行的 {ratio}）。
            严重度只用于排优先级，是否清洗由你定。
          </p>
        </div>

        <KpiStrip
          ariaLabel="体检结果概览"
          items={[
            {
              key: "total",
              label: "问题类型",
              value: issues.length,
              unit: "类",
              tone: stats.worst,
              dot: issues.length ? "warn" : "ok",
              note: issues.length ? "需要处理" : "未发现明显问题",
            },
            { key: "high", label: "高危", value: stats.high, unit: "类", tone: "danger", dot: stats.high ? "error" : "ok" },
            { key: "medium", label: "中危", value: stats.medium, unit: "类", tone: "warning", dot: stats.medium ? "warn" : "ok" },
            { key: "low", label: "低危", value: stats.low, unit: "类" },
            { key: "rows", label: "波及行数", value: fmtNum(stats.touched), unit: "行", note: `共 ${fmtNum(s.rowCount)} 行` },
            {
              key: "detector",
              label: "检测器异常",
              value: detectorErrors.length,
              unit: "项",
              tone: detectorErrors.length ? "warning" : "success",
              dot: detectorErrors.length ? "warn" : "ok",
            },
          ]}
        />

        {/* AI 列语义建议（未启用时不渲染任何入口；默认折叠、点开才请求） */}
        <AiColumnAdvice s={s} />

        <section className="panel panel--flush">
          <div className="panel__head" style={{ padding: "var(--pad-panel) var(--pad-panel) 0" }}>
            <h3 className="panel__title">问题清单</h3>
            <span className="panel__meta">
              {issues.length > 0 && (
                <Button size="sm" variant="secondary" onClick={addAllSuggested}>
                  一键加入全部建议步骤
                </Button>
              )}
            </span>
          </div>

          {issues.length === 0 ? (
            <div style={{ padding: "var(--space-4)" }}>
              <EmptyState
                icon="✓"
                title="未发现需要处理的问题"
                desc="9 类检测器均未报出问题，可直接导出原始数据，或按需自定义清洗。"
                action={
                  <Button variant="primary" onClick={() => s.goTo("recipe")}>
                    仍然要自定义清洗
                  </Button>
                }
              />
            </div>
          ) : (
            <IssueTable
              issues={issues}
              rowTotal={s.rowCount}
              onOpenDetail={setDetail}
              onAddSuggested={addSuggested}
            />
          )}
        </section>

        {detectorErrors.length > 0 && (
          <div className="detector-errors">
            <div className="detector-errors__title">{detectorErrors.length} 个检测器未给出结论</div>
            <ul>
              {detectorErrors.map((e, i) => (
                <li className="detector-errors__item" key={i}>
                  · {DETECTORS[e.issue_name]?.name ?? e.issue_name}：{e.message}
                </li>
              ))}
            </ul>
          </div>
        )}

        {s.columns.length > 0 && (
          <Collapse title="列名清单" meta={`${s.columns.length} 列 · 配方中按名称引用`}>
            <div className="chips">
              {s.columns.map((c) => (
                <span key={c} className="badge badge--neutral">{c}</span>
              ))}
            </div>
          </Collapse>
        )}
      </div>

      <WizardFooter hint="体检只读，不会改动数据">
        <Button variant="secondary" onClick={() => s.goTo("upload")}>上一步：上传</Button>
        <Button variant="primary" onClick={() => s.goTo("recipe")}>下一步：编写配方</Button>
      </WizardFooter>

      {detail && (
        <IssueDetailDrawer
          issue={detail}
          rowTotal={s.rowCount}
          onClose={() => setDetail(null)}
          onUseRecommended={addSuggested}
        />
      )}
    </>
  );
}
