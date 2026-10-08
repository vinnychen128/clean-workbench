// SPDX-License-Identifier: Apache-2.0
/** 报告屏顶部「人话摘要」折叠区块。
 *
 *  - 只读：不写任何结果字段、不影响导出与报告数值；
 *  - 默认折叠，**点开才请求**（省调用）；
 *  - 固定显示免责注「AI 生成，数值以上方表格为准」；
 *  - 未启用时不渲染该区块；失败（degraded）时展示单层来源标注 + 接口返回的本地规则兜底正文 + 重试，
 *    不阻塞报告其他功能；成功态渲染不变。
 */
import React, { useCallback, useState } from "react";
import { AiReportExplainResult, api } from "../api";
import { useAiStatus } from "../hooks/useAiStatus";
import { AI_DISCLAIMER, aiUnavailableText } from "../lib/ai";
import { Badge, Button, Collapse, Skeleton } from "./ui/primitives";

/** 降级态免责注：此时正文来自后端本地规则兜底（与 AI 无关），不得沿用「AI 生成」口径。 */
const FALLBACK_DISCLAIMER = "本地规则生成，数值以上方表格为准";

export function AiReportSummary({ threadId }: { threadId: string }) {
  const { available } = useAiStatus();
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<AiReportExplainResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    if (!threadId) return;
    setBusy(true);
    setErr(null);
    try {
      setRes(await api.aiReportExplain(threadId));
      setLoaded(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [threadId]);

  const copy = useCallback(async () => {
    if (!res?.text) return;
    try {
      await navigator.clipboard.writeText(`${res.text}\n\n（${res.disclaimer || AI_DISCLAIMER}）`);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }, [res]);

  if (!available) return null;

  const degraded = Boolean(res?.degraded);
  const text = res?.text ?? "";
  const disclaimer = res?.disclaimer || AI_DISCLAIMER;

  return (
    <section className="panel" style={{ marginBottom: "var(--space-4)" }}>
      <Collapse
        title="人话摘要"
        meta={
          !loaded && !busy
            ? "默认折叠 · 点开才请求"
            : degraded
              ? "AI 暂时不可用"
              : res?.cached
                ? "缓存"
                : "AI 生成"
        }
        onToggle={(open) => {
          if (open && !loaded && !busy) void load();
        }}
      >
        {busy && !res ? (
          <Skeleton h={72} />
        ) : err ? (
          <>
            <p className="muted">人话摘要获取失败：{err}</p>
            <Button size="sm" variant="secondary" onClick={() => void load()}>重试</Button>
          </>
        ) : degraded ? (
          <>
            <p className="muted">
              {aiUnavailableText(res?.reason)} · 以下为本地规则兜底摘要。上方表格数值与导出不受影响，可稍后重试。
            </p>
            {text && <p style={{ lineHeight: "var(--leading-loose)" }}>{text}</p>}
            <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", marginTop: "var(--space-3)", flexWrap: "wrap" }}>
              <Button size="sm" variant="secondary" onClick={() => void load()}>重试</Button>
              <Badge tone="warning">{FALLBACK_DISCLAIMER}</Badge>
            </div>
          </>
        ) : (
          <>
            <p style={{ lineHeight: "var(--leading-loose)" }}>{text}</p>
            <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", marginTop: "var(--space-3)", flexWrap: "wrap" }}>
              <Button size="sm" variant="ghost" onClick={() => void copy()}>
                {copied ? "已复制" : "复制"}
              </Button>
              <Badge tone="warning">{disclaimer}</Badge>
              {res?.model && <span className="muted">模型：{res.model}</span>}
            </div>
            <p className="muted settings__meta">本段仅为通俗解释，只读不改值；导出文件默认不含该文本。</p>
          </>
        )}
      </Collapse>
    </section>
  );
}
