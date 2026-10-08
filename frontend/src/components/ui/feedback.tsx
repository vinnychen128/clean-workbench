// SPDX-License-Identifier: Apache-2.0
/** 反馈类原子件：横幅 / 内联错误 / 进度 / KPI / 向导步骤条。
 *  与 primitives.tsx 同层，皮肤在 styles/components.css。 */
import React from "react";
import { Badge, StatusDot, StatusTone } from "./primitives";

/* ---------------- 横幅 ---------------- */

export function Banner({
  tone = "info",
  children,
  onDismiss,
}: {
  tone?: "info" | "warning" | "error" | "success";
  children: React.ReactNode;
  onDismiss?: () => void;
}) {
  const icon = tone === "error" ? "!" : tone === "warning" ? "!" : tone === "success" ? "✓" : "i";
  return (
    <div className={`banner banner--${tone}`} role={tone === "error" ? "alert" : "status"}>
      <span className="banner__icon" aria-hidden>{icon}</span>
      <span className="banner__text">{children}</span>
      {onDismiss && (
        <button className="banner__close" onClick={onDismiss} aria-label="关闭提示">✕</button>
      )}
    </div>
  );
}

export function ErrorBanner({ message, onDismiss }: { message: string; onDismiss?: () => void }) {
  return <Banner tone="error" onDismiss={onDismiss}>{message}</Banner>;
}

export function InfoBanner({ children }: { children: React.ReactNode }) {
  return <Banner tone="info">{children}</Banner>;
}

export function InlineError({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-error" role="alert">
      <span aria-hidden>!</span>
      <span>{children}</span>
    </span>
  );
}

/* ---------------- 进度 ---------------- */

export function MiniBar({
  value,
  max = 100,
  tone = "primary",
}: {
  value: number;
  max?: number;
  tone?: "primary" | "success" | "warning" | "danger";
}) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <span className="mini-bar" role="presentation">
      <span
        className={`mini-bar__fill${tone === "primary" ? "" : ` mini-bar__fill--${tone}`}`}
        style={{ width: `${pct}%` }}
      />
    </span>
  );
}

/** 不确定态进度（后端单次同步调用期间，不伪造百分比）。 */
export function InlineProgress({ label }: { label: React.ReactNode }) {
  return (
    <div className="inline-progress" aria-busy="true" aria-live="polite">
      <div className="inline-progress__meta">
        <span className="btn__spinner" aria-hidden />
        <span>{label}</span>
      </div>
      <span className="progressbar" aria-hidden>
        <span className="progressbar__fill" style={{ width: "35%", transition: "none" }} />
      </span>
    </div>
  );
}

/* ---------------- KPI ---------------- */

export interface KpiItem {
  key: string;
  label: string;
  value: React.ReactNode;
  unit?: string;
  note?: React.ReactNode;
  tone?: "neutral" | "primary" | "success" | "warning" | "danger";
  dot?: StatusTone;
}

export function KpiCard({ item }: { item: KpiItem }) {
  const tone = item.tone ?? "neutral";
  return (
    <div className={`kpi-card kpi-card--${tone}`}>
      <div className="kpi-card__label">
        {item.dot && <StatusDot tone={item.dot} />}
        <span>{item.label}</span>
      </div>
      <div className="kpi-card__value">
        {item.value}
        {item.unit && <span className="kpi-card__unit">{item.unit}</span>}
      </div>
      {item.note && <div className="kpi-card__note">{item.note}</div>}
    </div>
  );
}

export function KpiStrip({ items, ariaLabel }: { items: KpiItem[]; ariaLabel?: string }) {
  return (
    <div className="kpi-strip" role="group" aria-label={ariaLabel}>
      {items.map((it) => (
        <KpiCard key={it.key} item={it} />
      ))}
    </div>
  );
}

/* ---------------- 向导步骤条（七屏线性） ---------------- */

export interface WizardStep {
  key: string;
  label: string;
  reachable: boolean;
}

export function WizardStepper({
  steps,
  current,
  onJump,
}: {
  steps: WizardStep[];
  current: string;
  onJump: (key: string) => void;
}) {
  const curIdx = steps.findIndex((s) => s.key === current);
  return (
    <nav className="wizard-stepper" aria-label="流程步骤">
      {steps.map((s, i) => {
        const state = i === curIdx ? "active" : i < curIdx ? "done" : "todo";
        const blocked = !s.reachable && state !== "active";
        return (
          <React.Fragment key={s.key}>
            {i > 0 && <span className="wizard-stepper__line" data-done={i <= curIdx} aria-hidden />}
            <button
              type="button"
              className="wizard-stepper__item"
              data-state={blocked ? "blocked" : state}
              data-clickable={s.reachable && i !== curIdx}
              aria-current={i === curIdx ? "step" : undefined}
              disabled={!s.reachable}
              onClick={() => s.reachable && onJump(s.key)}
            >
              <span className="wizard-stepper__dot" aria-hidden>{i + 1}</span>
              <span className="wizard-stepper__label">{s.label}</span>
            </button>
          </React.Fragment>
        );
      })}
    </nav>
  );
}

/** 状态徽章（步骤卡右上角，文字 + 色彩双编码）。 */
export function StatusChip({
  status,
  label,
}: {
  status: "pending" | "ready" | "unknown" | "risky";
  label: string;
}) {
  if (status === "pending") return <span className="pending-chip">{label}</span>;
  const tone = status === "ready" ? "success" : status === "risky" ? "danger" : "neutral";
  return <Badge tone={tone}>{label}</Badge>;
}
