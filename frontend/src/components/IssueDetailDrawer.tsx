// SPDX-License-Identifier: Apache-2.0
/** 体检问题「行详情抽屉」（区块④ RowDetailDrawer）。
 *
 *  内容：问题说明 / 涉及行数 / 涉及行号（前 200 条 + 查看全部）/ 样本值（row·column·value 三列，只读）
 *  / 「用推荐操作处理」（等价的预填路径）。
 *
 *  样本值只读、只增：取后端返回的 `profile.issues[i].samples`（≤20 条，后端已脱敏），
 *  **绝不**按行号回索引原始数据 —— 列被清洗后行号会错位，那会给出比没有更糟的错值。
 */
import React from "react";
import { ProfileIssue } from "../api";
import { DETECTORS } from "../lib/ops";
import { pctOf } from "../lib/format";
import {
  Badge,
  Button,
  DrawerShell,
  ProgressiveList,
  SEVERITY_LABEL,
  fmtNum,
  severityBadge,
  useProgressive,
} from "./ui/primitives";

/** 行号展示上限：先铺 200 条，更多靠「显示全部」（行号可滚动到 200 条）。 */
const ROW_LIMIT = 200;

export interface IssueDetailDrawerProps {
  issue: ProfileIssue;
  /** 本次扫描总行数（占比分母） */
  rowTotal: number;
  onClose: () => void;
  /** 「用推荐操作处理」：带预填参数加入配方 */
  onUseRecommended: (issue: ProfileIssue) => void;
}

export function IssueDetailDrawer({ issue, rowTotal, onClose, onUseRecommended }: IssueDetailDrawerProps) {
  const spec = DETECTORS[issue.issue_name];
  const label = issue.label ?? spec?.name ?? issue.issue_name;
  const rows = issue.rows ?? [];
  const samples = issue.samples ?? [];
  const samplePage = useProgressive(samples, 20, 20);
  const total = (() => {
    const t = Number(issue.rows_total);
    if (Number.isFinite(t) && t > 0) return t;
    return rows.length;
  })();
  const ratio = pctOf(total, rowTotal);

  return (
    <DrawerShell title={`问题详情 · ${label}`} onClose={onClose} narrow>
      <div className="history-detail__head" style={{ marginBottom: "var(--space-3)" }}>
        <Badge tone={severityBadge(issue.severity)}>{SEVERITY_LABEL[issue.severity] ?? issue.severity}</Badge>
        <span className="muted">{spec?.desc ?? issue.issue_name}</span>
      </div>

      <div className="history-detail">
        <div className="muted">
          涉及行数：<span className="num">{fmtNum(total)}</span> 行
          {ratio ? `（占本次扫描 ${fmtNum(rowTotal)} 行的 ${ratio}）` : ""}
          {issue.column ? ` · 命中列：${issue.column}` : ""}
          {issue.columns && issue.columns.length > 0 ? ` · 命中列：${issue.columns.join("、")}` : ""}
        </div>
      </div>

      <div className="issue-group-title">样本值（后端脱敏，只读，最多 20 条）</div>
      {samples.length === 0 ? (
        <div className="muted">
          后端未给出该问题的样本值（可能整行级问题或未命中具体单元格）。样本值只从后端取，
          前端不按行号回索引原始数据，避免列被清洗后行号错位给出错值。
        </div>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th className="num" style={{ width: 80 }}>行号</th>
              <th style={{ width: 140 }}>列</th>
              <th>样本值</th>
            </tr>
          </thead>
          <tbody>
            {samplePage.shown.map((sp, i) => (
              <tr key={`${sp.row}-${i}`}>
                <td className="num">{sp.row}</td>
                <td className="mono">{sp.column ?? "—"}</td>
                <td className="mono">{sp.value === null || sp.value === "" ? "（空）" : String(sp.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="issue-group-title">涉及行号（原始数据 0 基行序）</div>
      {rows.length === 0 ? (
        <div className="muted">该问题未给出具体行号（按计数命中）。</div>
      ) : (
        <>
          <div className="rownums">
            <ProgressiveList
              items={rows}
              initial={ROW_LIMIT}
              step={ROW_LIMIT}
              getKey={(r) => r}
              renderItem={(r) => <span className="rownum">{r}</span>}
            />
          </div>
        </>
      )}

      <div style={{ marginTop: "var(--space-4)", display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
        {spec && (
          <Button variant="primary" size="sm" onClick={() => onUseRecommended(issue)}>
            用推荐操作处理（{spec.defaultOp}）
          </Button>
        )}
        <Button variant="secondary" size="sm" onClick={onClose}>
          关闭
        </Button>
      </div>
    </DrawerShell>
  );
}
