// SPDX-License-Identifier: Apache-2.0
/** 体检「问题表」—— 真实组件名 IssueTable（原 EdaScreen 内联表格抽出，行为等价、视觉不变）。
 *
 *  职责：列问题严重度 / 问题 / 涉及行数 / 占比 / 涉及行号 / 处置。
 *  - 占比口径：百分数 + 1 位小数，分母 = 本次扫描总行数（洗前数据规模）；
 *  - 行号只读（前 8 条），完整行号与样本值在行详情抽屉里看；
 *  - 处置按钮：一键把该问题的建议步骤加入配方（能唯一确定列则预填目标列）。
 *  - 长清单按「前 N 条 + 展开更多」渲染（数百行数据下不卡）。
 */
import React from "react";
import { ProfileIssue } from "../api";
import { DETECTORS } from "../lib/ops";
import { pctOf } from "../lib/format";
import {
  Badge,
  Button,
  SEVERITY_LABEL,
  fmtNum,
  severityBadge,
  useProgressive,
} from "./ui/primitives";

export interface IssueTableProps {
  issues: ProfileIssue[];
  /** 本次扫描的总行数（占比分母） */
  rowTotal: number;
  /** 点问题行 → 打开行详情抽屉 */
  onOpenDetail: (issue: ProfileIssue) => void;
  /** 加入建议步骤（带预填参数） */
  onAddSuggested: (issue: ProfileIssue) => void;
  /** 首批渲染条数（其余「展开更多」） */
  pageSize?: number;
}

function issueName(issue: ProfileIssue): string {
  return issue.label ?? DETECTORS[issue.issue_name]?.name ?? issue.issue_name;
}

function issueRows(issue: ProfileIssue): number[] {
  return issue.rows ?? [];
}

/** 命中行数：rows_total 优先（大数据量时后端 rows 可能只给前若干条 + 计数）。 */
function issueRowCount(issue: ProfileIssue): number {
  const total = Number(issue.rows_total);
  if (Number.isFinite(total) && total > 0) return total;
  return issueRows(issue).length;
}

export function IssueTable({
  issues,
  rowTotal,
  onOpenDetail,
  onAddSuggested,
  pageSize = 50,
}: IssueTableProps) {
  const p = useProgressive(issues, pageSize);
  const renderRow = (it: ProfileIssue) => {
    const rows = issueRows(it);
    const spec = DETECTORS[it.issue_name];
    const total = issueRowCount(it);
    return (
      <tr
        onClick={() => onOpenDetail(it)}
        title="查看问题详情、样本值与推荐处理"
        style={{ cursor: "pointer" }}
      >
        <td>
          <Badge tone={severityBadge(it.severity)}>
            {SEVERITY_LABEL[it.severity] ?? it.severity}
          </Badge>
        </td>
        <td>
          <div style={{ fontWeight: 600 }}>{issueName(it)}</div>
          <div className="muted">{spec?.desc ?? it.issue_name}</div>
        </td>
        <td className="num">{fmtNum(total)}</td>
        <td className="num">{pctOf(total, rowTotal) ?? "—"}</td>
        <td>
          <span className="rownums">
            {rows.slice(0, 8).map((r) => (
              <span className="rownum" key={r}>{r}</span>
            ))}
            {total > 8 && <span className="rownum rownum--more">+{total - 8}</span>}
          </span>
        </td>
        <td>
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            <Button size="sm" variant="ghost" onClick={() => onOpenDetail(it)}>
              查看样本
            </Button>
            {spec && (
              <Button size="sm" variant="secondary" onClick={() => onAddSuggested(it)}>
                加入配方（{spec.defaultOp}）
              </Button>
            )}
          </div>
        </td>
      </tr>
    );
  };

  return (
    <table className="table table--sticky">
      <thead>
        <tr>
          <th style={{ width: 84 }}>严重度</th>
          <th>问题</th>
          <th className="num" style={{ width: 100 }}>涉及行数</th>
          <th className="num" style={{ width: 84 }}>占比</th>
          <th style={{ width: 220 }}>涉及行号（前 8 行）</th>
          <th style={{ width: 220 }}>处置</th>
        </tr>
      </thead>
      <tbody>
        {p.shown.map((it) => (
          <React.Fragment key={it.issue_name}>{renderRow(it)}</React.Fragment>
        ))}
        {p.hasMore && (
          <tr>
            <td colSpan={6}>
              <div className="toolbar" style={{ marginBottom: 0 }}>
                <Button size="sm" variant="secondary" onClick={p.expand}>
                  {p.moreLabel}
                </Button>
                <Button size="sm" variant="ghost" onClick={p.expandAll}>
                  显示全部
                </Button>
                <span className="muted">{p.hint}</span>
              </div>
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}
