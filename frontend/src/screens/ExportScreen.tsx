// SPDX-License-Identifier: Apache-2.0
/** 屏 8「导出结果」：干净数据多格式落盘 + 报告 / 附件下载，
 *  每张卡片写明产物，防止"洗了不知道存哪"；导出记录逐条列明路径与附件。 */
import React, { useState } from "react";
import { WizardFooter } from "../components/AppShell";
import {
  Badge,
  Button,
  EmptyState,
  Select,
  TextInput,
  downloadJson,
  downloadText,
  formatClock,
  fmtNum,
} from "../components/ui/primitives";
import { InfoBanner, InlineError } from "../components/ui/feedback";
import { opLabel } from "../lib/ops";
import { Session } from "../hooks/useSession";

const DATA_FORMATS = [
  { value: "csv", label: "CSV（通用，推荐）" },
  { value: "xlsx", label: "Excel 工作簿 (.xlsx)" },
  { value: "ods", label: "OpenDocument 表格 (.ods)" },
  { value: "pdf", label: "PDF（只读留档）" },
  { value: "json", label: "JSON" },
  { value: "sql", label: "SQL INSERT" },
  { value: "template", label: "模板回填" },
];

function csvCell(v: unknown): string {
  const s = v === null || v === undefined ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

interface RepIssueLike {
  issue_name?: string;
  severity?: string;
  column?: string | null;
  rows?: number[];
}

export function ExportScreen({ s }: { s: Session }) {
  const [fmt, setFmt] = useState("csv");
  const [outDir, setOutDir] = useState("");

  const execution = s.exec;
  const base = (s.fileName || "clean").replace(/\.[^.]+$/, "");
  const tid8 = s.threadId.replace(/[^a-zA-Z0-9]/g, "").slice(-8) || "current";
  const issues: RepIssueLike[] =
    ((s.eda as unknown as { profile?: { issues?: RepIssueLike[] } })?.profile?.issues ?? []) as RepIssueLike[];

  function downloadIssuesCsv() {
    const rows: unknown[][] = [
      ["issue_name", "severity", "column", "affected_rows"],
      ...issues.map((i) => [i.issue_name ?? "", i.severity ?? "", i.column ?? "", (i.rows ?? []).length]),
    ];
    downloadText(`${base}_issues_${tid8}.csv`, rows.map((r) => r.map(csvCell).join(",")).join("\n"), "text/csv;charset=utf-8");
  }

  function downloadRecipeJson() {
    if (!s.plan) return;
    downloadJson(`${base}_recipe_${tid8}.json`, s.plan);
  }

  async function downloadReportMd() {
    const md = s.reportMd || ((await s.loadReport("md")) as string) || "";
    if (md) downloadText(`${base}_report_${tid8}.md`, md, "text/markdown;charset=utf-8");
  }

  async function downloadReportJson() {
    const data = s.reportJson ?? (await s.loadReport("json"));
    if (data) downloadJson(`${base}_report_${tid8}.json`, data);
  }

  return (
    <>
      <div className="screen screen--max">
        <div className="screen-head">
          <h2 className="screen-q">第八步：导出结果</h2>
          <p className="screen-sub">
            数据不会上传外部服务；干净数据由本地后端写入所选目录并留档（导出记录里给出完整路径），
            辅助文件（问题明细 / 配方）可直接下载到浏览器下载目录。
          </p>
        </div>

        {!execution && (
          <section className="panel">
            <EmptyState
              icon="⇩"
              title="暂无可导出的结果"
              desc="请先在执行进度屏完成一次清洗。"
              action={
                <Button variant="primary" onClick={() => s.goTo("execute")}>
                  回执行屏
                </Button>
              }
            />
          </section>
        )}

        {execution && (
          <>
            <section className="panel">
              <div className="panel__head">
                <span className="panel__title">输出位置</span>
                <span className="panel__meta">
                  {fmtNum(execution.rows.length)} 行 × {execution.columns.length} 列待导出
                </span>
              </div>
              <div className="toolbar" style={{ marginBottom: "var(--space-2)" }}>
                <TextInput
                  value={outDir}
                  onChange={setOutDir}
                  placeholder="输出目录绝对路径，留空使用后端默认输出目录"
                  ariaLabel="输出目录"
                />
                <Select value={fmt} onChange={setFmt} options={DATA_FORMATS} ariaLabel="干净数据格式" />
              </div>
              <InfoBanner>
                留空输出目录时，后端会写入其默认输出目录（返回结果里会给出完整路径）；勾选附件会同时落盘问题明细、
                问题汇总与配方 JSON，且与主文件同目录。
              </InfoBanner>
            </section>

            <div className="export-grid">
              <section className="export-card">
                <div className="export-card__title">干净数据</div>
                <div className="export-card__desc">
                  按上方所选格式写入本机目录，兼容 Excel / 数据库 / 留档阅读。
                </div>
                <div className="export-card__row">
                  <Button
                    variant="primary"
                    loading={s.exportBusy === fmt}
                    onClick={() => void s.doExport(fmt, { outDir, attachments: false })}
                  >
                    保存到本机目录（{fmt.toUpperCase()}）
                  </Button>
                </div>
                <div className="export-card__row">
                  {/* 缺陷修复②：原实现直接在前端拼 CSV 触发浏览器下载，既无进行中反馈，也不产生落盘记录。
                      现与「保存到本机目录」同一条链路（后端写盘 + 导出记录 + 成功横幅）。 */}
                  <Button
                    variant="ghost"
                    loading={s.exportBusy === "csv-local"}
                    onClick={() =>
                      void s.doExport("csv", { outDir, attachments: false, busyKey: "csv-local" })
                    }
                  >
                    本地下载 CSV
                  </Button>
                </div>
              </section>

              <section className="export-card">
                <div className="export-card__title">清洗报告</div>
                <div className="export-card__desc">三段式报告，可交付给业务方或存档；Markdown 便于二次编辑。</div>
                <div className="export-card__row">
                  <Button variant="secondary" loading={s.reportBusy} onClick={() => void downloadReportMd()}>
                    下载 Markdown
                  </Button>
                  <Button variant="ghost" onClick={() => void downloadReportJson()}>
                    下载 JSON
                  </Button>
                </div>
              </section>

              <section className="export-card">
                <div className="export-card__title">附件（问题明细 / 汇总 / 配方）</div>
                <div className="export-card__desc">
                  以 CSV 主文件落盘的同时，附带问题明细、问题汇总与配方 JSON 三份附件。
                </div>
                <div className="export-card__row">
                  <Button
                    variant="secondary"
                    loading={s.exportBusy === "csv"}
                    onClick={() => void s.doExport("csv", { outDir, attachments: true })}
                  >
                    保存主文件 + 三份附件
                  </Button>
                </div>
                <div className="export-card__row">
                  <Button variant="ghost" disabled={issues.length === 0} onClick={downloadIssuesCsv}>
                    本地下载问题明细 CSV
                  </Button>
                  <Button variant="ghost" disabled={!s.plan} onClick={downloadRecipeJson}>
                    本地下载配方 JSON
                  </Button>
                </div>
              </section>
            </div>

            {s.error && (
              <section className="panel">
                <InlineError>{s.error}</InlineError>
              </section>
            )}

            <section className="panel">
              <div className="panel__head">
                <span className="panel__title">落盘记录</span>
                <span className="panel__meta">{s.exports.length} 条</span>
              </div>
              {s.exports.length === 0 ? (
                <EmptyState icon="⇩" title="还没有导出记录" desc="任何一次成功导出都会在这里留档（含附件路径）。" />
              ) : (
                <>
                  <table className="table">
                    <thead>
                      <tr>
                        <th>格式</th>
                        <th>主文件</th>
                        <th className="num">附件</th>
                        <th>时间</th>
                      </tr>
                    </thead>
                    <tbody>
                      {s.exports.map((e, i) => (
                        <tr key={`${e.path}-${i}`}>
                          <td>
                            <Badge tone="primary">{e.format.toUpperCase()}</Badge>
                          </td>
                          <td className="mono">{e.path}</td>
                          <td className="num">{e.extra.length}</td>
                          <td className="num">{formatClock(e.at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {s.exports.some((e) => e.extra.length > 0) && (
                    <div style={{ marginTop: "var(--space-4)" }}>
                      <div className="export-results__title">附件清单</div>
                      {s.exports
                        .filter((e) => e.extra.length > 0)
                        .map((e, i) => (
                          <div className="export-results" key={`extra-${i}`}>
                            <div className="export-results__title">主文件：{e.path}</div>
                            <ul>
                              {e.extra.map((f) => (
                                <li key={f}>
                                  <Badge tone="neutral">附件</Badge>
                                  <span className="mono">{f}</span>
                                </li>
                              ))}
                            </ul>
                          </div>
                        ))}
                    </div>
                  )}
                </>
              )}
              {execution.transform_log.length > 0 && (
                <p className="muted" style={{ marginTop: "var(--space-3)" }}>
                  共 {execution.transform_log.length} 个清洗步骤
                  {execution.transform_log[0]?.op
                    ? `（首步：${opLabel(execution.transform_log[0].op)}）`
                    : ""}
                  。
                </p>
              )}
            </section>
          </>
        )}
      </div>

      <WizardFooter
        hint={
          s.exports.length > 0
            ? `已导出 ${s.exports.length} 次，可继续导出其他格式`
            : "选择格式与目录后导出，主文件会给出完整路径"
        }
      >
        <Button variant="secondary" onClick={() => s.goTo("report")}>
          上一步：查看报告
        </Button>
        <Button variant="ghost" onClick={() => s.reset()}>
          完成，清洗下一份
        </Button>
      </WizardFooter>
    </>
  );
}
