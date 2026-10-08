// SPDX-License-Identifier: Apache-2.0
/** 屏 5「确认门」：单一问题 = 是否按这个方案改数据。
 *  展示配方步骤顺序 + 影响范围 + 风险提示，必须勾选知悉后才能确认执行（人工确认门）。
 *
 *  实现说明（「知情放行」+ 同一判据）：
 *  - 存在未覆盖高危项时不再"卡死自己"：二级确认「我已知情，仍要继续」→ 展开必填说明（≥5 字）
 *    + 复选框「我理解该风险由我承担」，两项齐备才可放行；
 *  - 放行时带 `override:{ack:true, skipped:[issue_name...], note}` 重发 /api/confirm；
 *  - 说明不足由后端返回 409 `OVERRIDE_NOTE_REQUIRED`，前端**就地**提示（不弹新窗、不丢输入）；
 *  - 后端 409 `COVERAGE_BLOCKED` 时展示 `detail.uncovered_high[]`（中文名 / 波及行数 / 可用操作）；
 *  - 判据与后端同一份（`reporter.HANDLED_BY_OPS`，见 useSession.ISSUE_HANDLERS 注释）。
 */
import React, { useEffect, useRef, useState } from "react";
import { WizardFooter } from "../components/AppShell";
import { Badge, Button, TextInput } from "../components/ui/primitives";
import { EmptyState } from "../components/ui/primitives";
import { InlineError } from "../components/ui/feedback";
import { DETECTORS, riskFlagMatchesStep } from "../lib/ops";
import { unmetMessageText } from "../lib/format";
import { fmtNum } from "../components/ui/primitives";
import { Session } from "../hooks/useSession";

/** 说明最少字数（与后端 `len(note.strip()) < 5` 同一门槛）。 */
const OVERRIDE_NOTE_MIN = 5;

export function HitlScreen({ s }: { s: Session }) {
  /* 缺陷修复①：受控 checkbox 在真实点击后偶发状态未同步（放行按钮读到旧值，勾了也不放行）。
     改为「事件层同步」——以 DOM checkbox 为唯一真值源，onChange / onClick 双事件回写，
     放行前再取一次 DOM 真值，杜绝渲染时序导致的「已勾选却仍被拦住」。 */
  const ackRef = useRef<HTMLInputElement>(null);
  const [ack, setAck] = useState(false);
  const [reason, setReason] = useState("");
  const syncAck = () => setAck(!!ackRef.current?.checked);
  const ackTruthy = () => ackRef.current?.checked ?? ack;

  /* 二级确认（知情放行）本地态。 */
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideNote, setOverrideNote] = useState("");
  const [overrideChecked, setOverrideChecked] = useState(false);

  /* 配方换了 / 阻断解除后，本地的二级确认态不得残留。 */
  useEffect(() => {
    setOverrideOpen(false);
    setOverrideNote("");
    setOverrideChecked(false);
  }, [s.plan?.recipe_id]);

  if (!s.plan) {
    return (
      <>
        <div className="screen screen--wizard">
          <div className="screen-head">
            <h2 className="screen-q">第五步：确认这份清洗方案</h2>
            <p className="screen-sub">确认门需要先有一份已生成的配方。</p>
          </div>
          <section className="panel">
            <EmptyState
              icon="◫"
              title="还没有可确认的配方"
              desc="回到配方屏排好步骤并生成配方后，这里会给出影响范围与风险提示。"
              action={
                <Button variant="primary" onClick={() => s.goTo("recipe")}>去编写配方</Button>
              }
            />
          </section>
        </div>
        <WizardFooter hint="需要先生成配方" width="wizard">
          <Button variant="secondary" onClick={() => s.goTo("recipe")}>上一步：配方</Button>
          <Button variant="primary" disabled>确认执行</Button>
        </WizardFooter>
      </>
    );
  }

  const riskFlags = s.plan.risk_flags ?? [];
  /* 缺陷修复③：风险项计数纳入体检高危项；存在未达标高危项时阻断放行。 */
  const riskCount = s.riskGate.riskItemCount;
  const gateBlocked = s.riskGate.blocked;
  /* 未覆盖高危项 —— 后端 409 给的 detail.uncovered_high 优先（最终闸门口径），
     没有时用本地 riskGate 明细（立即提示，不用等一趟网络往返）。 */
  const uncovered = s.coverageBlock?.uncoveredHigh?.length
    ? s.coverageBlock.uncoveredHigh
    : s.riskGate.uncoveredHighIssues.map((h) => ({
        issue_name: h.issue_name,
        /* 界面问题名统一取前端检测器注册表（lib/ops.ts::DETECTORS），
           与体检屏 / 问题表 / 报告屏同一份；后端 label 只作兜底。 */
        label: DETECTORS[h.issue_name]?.name ?? h.label,
        severity: h.severity,
        affected_rows: h.affected_rows,
        handlers: h.handlers,
        message: h.message,
      }));
  const noteLen = overrideNote.trim().length;
  const noteOk = noteLen >= OVERRIDE_NOTE_MIN;
  const overrideReady = overrideChecked && noteOk;
  const canConfirmDirect = ack && !gateBlocked;
  const canConfirm = canConfirmDirect || (gateBlocked && overrideReady);

  /** 确认执行：正常路径不带 override；阻断路径带 override（ack + 跳过项 + 说明）。 */
  const onConfirm = () => {
    if (gateBlocked) {
      if (!overrideReady) {
        s.setInfo("");
        s.setError(`请先勾选「我理解该风险由我承担」并填写跳过原因（≥${OVERRIDE_NOTE_MIN} 字）。`);
        return;
      }
      void s.decide(true, reason, {
        ack: true,
        skipped: uncovered.map((u) => u.issue_name),
        note: overrideNote.trim(),
      });
      return;
    }
    if (!ackTruthy()) return;
    void s.decide(true, reason);
  };

  return (
    <>
      <div className="screen screen--wizard">
        <div className="screen-head">
          <h2 className="screen-q">第五步：确认这份清洗方案</h2>
          <p className="screen-sub">确认后才会改动数据；驳回则回配方屏继续调整，原文件始终不被覆盖。</p>
        </div>

        <div className="summary-bar" role="status" aria-label="影响范围">
          <div className="summary-bar__item">
            <span className="summary-bar__label">配方步骤</span>
            <span className="summary-bar__value">{s.plan.steps.length} 步</span>
          </div>
          <div className="summary-bar__item">
            <span className="summary-bar__label">影响数据</span>
            <span className="summary-bar__value">
              {s.rowCount.toLocaleString("zh-CN")} 行 × {s.columns.length} 列
            </span>
          </div>
          <div className="summary-bar__item">
            <span className="summary-bar__label">风险项</span>
            <span className="summary-bar__value" style={{ color: riskCount ? "var(--danger-600)" : undefined }}>
              {riskCount} 项
            </span>
          </div>
        </div>

        <section className="panel">
          <div className="panel__head">
            <h3 className="panel__title">执行顺序</h3>
            <span className="panel__meta muted">配方 {s.plan.recipe_id.slice(0, 8)}</span>
          </div>
          <div className="recipe-steps recipe-steps--compact">
            {s.picked.map((p, i) => {
              const risky = s.derived.statuses[i] === "risky";
              const flag = riskFlags.find((f) => riskFlagMatchesStep(f, i));
              return (
                <div className="recipe-step" key={`${p.op}-${i}`}>
                  <span className="recipe-step__idx">{i + 1}</span>
                  <span className="recipe-step__text">
                    {s.plan?.description[i] ?? p.op}
                    {risky && <Badge tone="danger">需重点确认</Badge>}
                    {flag && <span className="muted"> · {flag}</span>}
                  </span>
                </div>
              );
            })}
          </div>

          {riskFlags.length > 0 && (
            <ul className="risk-flags">
              <li className="risk-flags__title">检测到 {riskFlags.length} 条风险提示</li>
              {riskFlags.map((f, i) => (
                <li key={i}>
                  <Badge tone="warning">风险</Badge>
                  <span>{f}</span>
                </li>
              ))}
            </ul>
          )}

          <div className="confirm-gate" style={{ marginTop: "var(--space-5)" }}>
            <div className="confirm-gate__banner">
              <span className="confirm-gate__lock" aria-hidden>⚠</span>
              <span>
                执行会在本机生成清洗结果，不会覆盖你的原始文件。确认前请核对步骤顺序与影响范围；
                高危步骤（删行 / 删列 / 去重）请特别留意。
              </span>
            </div>

            {gateBlocked && (
              <div className="unmet" style={{ marginTop: "var(--space-3)" }}>
                <div className="unmet__title">
                  已阻断放行：{s.riskGate.uncoveredHighCount} 项体检高危问题未被配方覆盖（未达标）
                </div>
                <ul>
                  {uncovered.map((h) => (
                    <li key={h.issue_name}>
                      {h.label}
                      {h.affected_rows ? `（波及 ${fmtNum(h.affected_rows)} 行）` : ""}
                      {h.handlers && h.handlers.length > 0
                        ? `（可用操作：${h.handlers.join(" / ")}）`
                        : "（无可用操作，只能由你判断如何处理）"}
                    </li>
                  ))}
                </ul>
                {s.coverageBlock?.message && (
                  <p className="muted" style={{ marginTop: "var(--space-2)" }}>
                    后端覆盖校验：{unmetMessageText(s.coverageBlock.message)}
                  </p>
                )}
              </div>
            )}

            {/* 阻断状态下的二级确认（知情放行）—— 说明必填 ≥5 字 + 勾选承担风险 */}
            {gateBlocked && (
              <div style={{ marginTop: "var(--space-3)" }}>
                {!overrideOpen ? (
                  <Button variant="secondary" size="sm" onClick={() => setOverrideOpen(true)}>
                    我已知情，仍要继续
                  </Button>
                ) : (
                  <div className="confirm-gate__banner" style={{ display: "block" }}>
                    <div className="unmet__title" style={{ marginBottom: "var(--space-2)" }}>
                      知情放行：以下 {uncovered.length} 项将保持原样不处理，并记入报告「未处理项」
                    </div>
                    <ul>
                      {uncovered.map((h) => (
                        <li key={`ov-${h.issue_name}`} className="muted">
                          {h.label} · 波及 {fmtNum(h.affected_rows)} 行
                        </li>
                      ))}
                    </ul>
                    <div style={{ marginTop: "var(--space-3)" }}>
                      <TextInput
                        value={overrideNote}
                        onChange={setOverrideNote}
                        placeholder={`跳过原因（必填，≥${OVERRIDE_NOTE_MIN} 字，写入报告留痕）`}
                        ariaLabel="跳过原因（≥5 字）"
                        invalid={noteLen > 0 && !noteOk}
                      />
                      <div className="muted" style={{ marginTop: "var(--space-1)" }}>
                        已填 {noteLen} 字（需 ≥{OVERRIDE_NOTE_MIN} 字）
                        {noteLen > 0 && !noteOk ? " —— 说明太短，还不够放行。" : ""}
                      </div>
                    </div>
                    {s.overrideNoteError && (
                      <div style={{ marginTop: "var(--space-2)" }}>
                        <InlineError>{s.overrideNoteError}</InlineError>
                      </div>
                    )}
                    <label
                      style={{
                        display: "inline-flex",
                        gap: "var(--space-2)",
                        alignItems: "center",
                        marginTop: "var(--space-3)",
                        fontSize: "var(--text-sm)",
                        color: "var(--ink-700)",
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={overrideChecked}
                        onChange={(e) => setOverrideChecked(e.target.checked)}
                      />
                      我理解该风险由我承担
                    </label>
                    <div className="toolbar" style={{ marginTop: "var(--space-3)", marginBottom: 0 }}>
                      <Button
                        variant="danger"
                        size="sm"
                        disabled={!overrideReady}
                        loading={s.confirmBusy}
                        title={overrideReady ? undefined : `需填写 ≥${OVERRIDE_NOTE_MIN} 字说明并勾选承担风险`}
                        onClick={onConfirm}
                      >
                        确认放行（知情）
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setOverrideOpen(false);
                          setOverrideNote("");
                          setOverrideChecked(false);
                          s.clearOverrideHint();
                        }}
                      >
                        取消，回配方补齐
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            )}

            <label
              style={{
                display: "inline-flex",
                gap: "var(--space-2)",
                alignItems: "center",
                fontSize: "var(--text-sm)",
                color: "var(--ink-700)",
              }}
            >
              <input
                ref={ackRef}
                type="checkbox"
                defaultChecked={false}
                onChange={syncAck}
                onClick={syncAck}
              />
              我已核对步骤顺序与影响范围，确认按该配方执行
            </label>

            <div className="confirm-gate__actions">
              <span className="confirm-gate__reason">
                <TextInput
                  value={reason}
                  onChange={setReason}
                  placeholder="驳回原因 / 备注（可选，写入审计留痕）"
                  ariaLabel="驳回原因"
                />
              </span>
              <Button
                variant="secondary"
                loading={s.confirmBusy}
                onClick={() => void s.decide(false, reason)}
              >
                驳回并返回配方
              </Button>
              <Button
                variant="danger"
                disabled={!canConfirm}
                loading={s.confirmBusy}
                title={
                  gateBlocked
                    ? `已阻断放行：${s.riskGate.uncoveredHighCount} 项体检高危问题未被配方覆盖（未达标），可点「我已知情，仍要继续」填写说明后放行`
                    : undefined
                }
                onClick={onConfirm}
              >
                确认执行
              </Button>
            </div>
          </div>
        </section>
      </div>

      <WizardFooter
        hint={
          gateBlocked
            ? `已阻断放行：${s.riskGate.uncoveredHighCount} 项体检高危问题未被配方覆盖（未达标）；可补齐配方，或点「我已知情，仍要继续」填写说明后放行`
            : ack
              ? "已勾选知悉，可以确认执行"
              : "请先核对方案并勾选知悉"
        }
        width="wizard"
      >
        <Button variant="secondary" onClick={() => s.goTo("recipe")}>返回配方调整</Button>
        <Button
          variant="danger"
          disabled={!canConfirm}
          loading={s.confirmBusy}
          title={
            gateBlocked
              ? `已阻断放行：${s.riskGate.uncoveredHighCount} 项体检高危问题未被配方覆盖（未达标），可点「我已知情，仍要继续」填写说明后放行`
              : undefined
          }
          onClick={onConfirm}
        >
          确认执行
        </Button>
      </WizardFooter>
    </>
  );
}
