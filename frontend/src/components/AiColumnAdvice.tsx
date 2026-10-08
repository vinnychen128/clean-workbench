// SPDX-License-Identifier: Apache-2.0
/** 数据体检屏的「AI 建议」区。
 *
 *  三态：
 *  - 未启用 → 整个区块**不渲染**（不占版面，不出现空白块）；
 *  - 正常 → 默认折叠；**点开才请求**（未点开不调用），逐列展示语义类型 + 依据 +
 *    建议算子，人工点「加入配方」才把该建议转成标准配方步骤（值仍由算子改）；
 *  - 失败/降级 → 显示原因 + 重试，不阻塞体检屏其他功能。
 */
import React, { useCallback, useState } from "react";
import { AiColumnAdviceResult, api } from "../api";
import { Session } from "../hooks/useSession";
import { useAiStatus } from "../hooks/useAiStatus";
import { aiUnavailableText } from "../lib/ai";
import { Badge, Button, Collapse, Skeleton } from "./ui/primitives";

export function AiColumnAdvice({ s }: { s: Session }) {
  const { available } = useAiStatus();
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<AiColumnAdviceResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [adding, setAdding] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!s.threadId) return;
    setBusy(true);
    setErr(null);
    try {
      setRes(await api.aiColumnAdvice(s.threadId));
      setLoaded(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [s.threadId]);

  /** 人确认后追加配方：后端校验算子名/参数与列名，只追加配方、不写数据、不执行。 */
  const accept = useCallback(
    async (column: string, op: string, params: Record<string, unknown>) => {
      const key = `${column}|${op}`;
      setAdding(key);
      setMsg(null);
      try {
        const r = await api.aiAcceptAdvice(s.threadId, column, op, params ?? {});
        if (r.ok) {
          const step = (r.step ?? { op, params }) as { op: string; params?: Record<string, unknown> };
          s.addOp(step.op, step.params ?? {});
          s.setInfo(
            `已加入配方：${column} · ${step.op}` +
              (r.recipe_step_index != null ? `（第 ${r.recipe_step_index} 步，待人工确认后执行）` : ""),
          );
        } else {
          setMsg(`加入配方失败：${r.reason === "unknown_op" ? "算子不在既有目录内" : r.reason ?? "校验未通过"}`);
        }
      } catch (e) {
        setMsg(e instanceof Error ? e.message : String(e));
      } finally {
        setAdding(null);
      }
    },
    [s],
  );

  /* 未启用（含状态读取中）一律不渲染任何 AI 入口。 */
  if (!available) return null;

  const advice = res?.advice ?? [];
  const degraded = Boolean(res?.degraded);

  return (
    <section className="panel" style={{ marginTop: "var(--space-4)" }}>
      <Collapse
        title="AI 建议（列语义与方案）"
        meta={
          !loaded && !busy
            ? "默认折叠 · 点开才请求"
            : degraded
              ? "无 AI 建议"
              : `${advice.length} 列`
        }
        onToggle={(open) => {
          if (open && !loaded && !busy) void load();
        }}
      >
        {busy && !res ? (
          <Skeleton h={72} />
        ) : err ? (
          <>
            <p className="muted">AI 建议获取失败：{err}</p>
            <Button size="sm" variant="secondary" onClick={() => void load()}>重试</Button>
          </>
        ) : degraded ? (
          <>
            <p className="muted">{aiUnavailableText(res?.reason)}。体检结果不受影响，可稍后重试。</p>
            <Button size="sm" variant="secondary" onClick={() => void load()}>重试</Button>
          </>
        ) : advice.length === 0 ? (
          <p className="muted">暂无建议（空数组表示各列无需处理）。</p>
        ) : (
          <>
            <p className="muted" style={{ marginBottom: "var(--space-2)" }}>
              以下均为建议：模型只读列的形态，值仍由既有算子修改，需你点「加入配方」才会生效。
            </p>
            {advice.map((a) => (
              <Collapse
                key={a.column}
                title={a.column}
                meta={
                  <>
                    <Badge tone="neutral">{a.semantic_type}</Badge>
                    {a.cached && <span className="muted">缓存</span>}
                  </>
                }
              >
                {a.evidence?.length > 0 && (
                  <p className="muted">依据：{a.evidence.join(" · ")}</p>
                )}
                <p>{a.rationale}</p>
                {a.suggested_ops?.length > 0 ? (
                  <ul className="settings__list">
                    {a.suggested_ops.map((op) => {
                      const key = `${a.column}|${op.op}`;
                      return (
                        <li key={op.op}>
                          <code className="mono">{op.op}</code>
                          {op.params && Object.keys(op.params).length > 0 && (
                            <code className="mono">{JSON.stringify(op.params)}</code>
                          )}
                          <Button
                            size="sm"
                            variant="secondary"
                            loading={adding === key}
                            onClick={() => void accept(a.column, op.op, op.params ?? {})}
                          >
                            加入配方
                          </Button>
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <p className="muted">该列无需处理。</p>
                )}
                <p className="muted">
                  置信度 {Math.round((a.confidence ?? 0) * 100)}%（仅用于排序展示，不参与自动执行）
                </p>
              </Collapse>
            ))}
            {msg && <p className="muted">{msg}</p>}
          </>
        )}
      </Collapse>
    </section>
  );
}
