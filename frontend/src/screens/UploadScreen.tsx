// SPDX-License-Identifier: Apache-2.0
/** 屏 1「上传」：单一问题 = 数据在哪。
 * 拖放/点选 → 浏览器本地读取 → 本机服务解析 → 显示行列/编码/告警；原件不出本机。 */
import React, { useRef, useState } from "react";
import { WizardFooter } from "../components/AppShell";
import { Badge, Button, Collapse, EmptyState, formatBytes } from "../components/ui/primitives";
import { InlineProgress, KpiStrip } from "../components/ui/feedback";
import { DETECTORS } from "../lib/ops";
import { Session } from "../hooks/useSession";

const ACCEPT = ".csv,.tsv,.xlsx,.xls,.txt,.json";

export function UploadScreen({ s }: { s: Session }) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const pick = (files: FileList | null) => {
    const f = files?.[0];
    if (f) void s.parse(f);
  };

  const warnCount = s.parsingReport?.warnings?.length ?? 0;

  return (
    <>
      <div className="screen screen--max">
        <div className="screen-head">
          <h2 className="screen-q">第一步：把要清洗的数据丢进来</h2>
          <p className="screen-sub">
            浏览器本地读取文件内容后交给本机服务解析，文件不上传互联网；解析完成后即可体检。
          </p>
        </div>

        <div className="grid-2">
          <section className="panel">
            <div className="panel__head">
              <h3 className="panel__title">选择数据文件</h3>
              <span className="panel__meta muted">CSV / TSV / XLSX / XLS / TXT / JSON</span>
            </div>

            <div
              className={`dropzone${dragOver ? " is-dragover" : ""}`}
              role="button"
              tabIndex={0}
              aria-label="选择或拖入数据文件"
              onClick={() => inputRef.current?.click()}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
              }}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                pick(e.dataTransfer.files);
              }}
            >
              <span className="dropzone__icon" aria-hidden>⬆</span>
              <span className="dropzone__title">{s.parseBusy ? "正在解析…" : "拖入文件，或点击选择"}</span>
              <span className="dropzone__sub">单个文件，建议 ≤ 50 MB</span>
              <span className="dropzone__local">本机解析，原文不上传</span>
              <input
                ref={inputRef}
                type="file"
                accept={ACCEPT}
                style={{ display: "none" }}
                onChange={(e) => pick(e.target.files)}
              />
            </div>

            {s.parseBusy && (
              <div className="parse-progress">
                <InlineProgress label="正在读取并解析文件…" />
              </div>
            )}

            {s.threadId && (
              <div className="parse-progress">
                <div className="file-chip">
                  <span className="file-chip__icon" aria-hidden>▤</span>
                  <span className="file-chip__body">
                    <span className="file-chip__name">{s.fileName}</span>
                    <span className="file-chip__meta">
                      {formatBytes(s.fileSize)} · 会话 {s.threadId.slice(0, 8)} · 已解析
                    </span>
                  </span>
                  <Badge tone="success">解析完成</Badge>
                </div>

                <KpiStrip
                  ariaLabel="解析结果概览"
                  items={[
                    { key: "rows", label: "数据行", value: s.rowCount.toLocaleString("zh-CN"), unit: "行", tone: "primary" },
                    { key: "cols", label: "数据列", value: s.colCount, unit: "列" },
                    { key: "encoding", label: "识别编码", value: s.parsingReport?.encoding ?? "—" },
                    {
                      key: "warn",
                      label: "解析告警",
                      value: warnCount,
                      unit: "条",
                      tone: warnCount > 0 ? "warning" : "success",
                      dot: warnCount > 0 ? "warn" : "ok",
                    },
                  ]}
                />

                {warnCount > 0 && (
                  <Collapse title="解析告警详情" meta={`${warnCount} 条`}>
                    <ul>
                      {s.parsingReport?.warnings?.map((w, i) => (
                        <li key={i} className="muted">· {w}</li>
                      ))}
                    </ul>
                  </Collapse>
                )}

                {s.columns.length > 0 && (
                  <Collapse title="列名清单" meta={`${s.columns.length} 列`}>
                    <div className="chips">
                      {s.columns.map((c) => (
                        <span key={c} className="badge badge--neutral">{c}</span>
                      ))}
                    </div>
                  </Collapse>
                )}
              </div>
            )}

            {!s.threadId && !s.parseBusy && (
              <div className="parse-progress">
                <EmptyState
                  icon="▤"
                  title="还没有数据"
                  desc="选择一份表格文件后，这里会显示行列规模、识别编码与解析告警。"
                />
              </div>
            )}
          </section>

          <section className="panel">
            <div className="panel__head">
              <h3 className="panel__title">这次会替你查什么</h3>
            </div>
            <p className="muted" style={{ marginBottom: "var(--space-4)" }}>
              体检阶段会跑满 9 类问题检测器，只读不改；扫完给出问题清单与建议清洗步骤。
            </p>
            <ul className="settings__list">
              {Object.entries(DETECTORS).map(([key, d]) => (
                <li key={key}>
                  <Badge tone="primary">{d.name}</Badge>
                  <span className="muted">{d.desc}</span>
                </li>
              ))}
            </ul>
            <div className="banner banner--info" style={{ marginTop: "var(--space-5)" }}>
              <span className="banner__icon" aria-hidden>i</span>
              <span className="banner__text">
                数据只在本机流转：页面仅调用 127.0.0.1:8321 的本地服务，无云端上传、无遥测统计。
              </span>
            </div>
          </section>
        </div>
      </div>

      <WizardFooter hint={s.threadId ? "解析完成，可以开始体检" : "先选择一份数据文件"}>
        <Button variant="secondary" disabled={s.parseBusy} onClick={() => inputRef.current?.click()}>
          重新选择文件
        </Button>
        <Button variant="primary" disabled={!s.threadId} loading={s.edaBusy} onClick={() => void s.runEda()}>
          开始体检
        </Button>
      </WizardFooter>
    </>
  );
}
