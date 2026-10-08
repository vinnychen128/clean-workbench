// SPDX-License-Identifier: Apache-2.0
/** 应用骨架：顶栏 + 向导步骤条 + 全局横幅槽 + 屏幕容器 + 常驻页脚。
 *  屏幕内容由 screens/* 注入；页脚由各屏按自身状态渲染（WizardFooter）。 */
import React from "react";
import { Badge, StatusDot, Tooltip } from "./ui/primitives";
import { WizardStepper } from "./ui/feedback";
import { SCREENS, ScreenKey, Session } from "../hooks/useSession";

export function WizardFooter({
  hint,
  width = "max",
  children,
}: {
  hint?: React.ReactNode;
  width?: "max" | "wizard";
  children: React.ReactNode;
}) {
  return (
    <footer className="wizard-footer">
      <div className={`wizard-footer__inner wizard-footer__inner--${width}`}>
        {hint && <span className="wizard-footer__hint">{hint}</span>}
        <span className="wizard-footer__spacer" />
        <span className="wizard-footer__actions">{children}</span>
      </div>
    </footer>
  );
}

export function AppShell({
  s,
  onOpenHistory,
  onOpenSettings,
  children,
}: {
  s: Session;
  onOpenHistory: () => void;
  onOpenSettings: () => void;
  children: React.ReactNode;
}) {
  const steps = SCREENS.map((sc) => ({
    key: sc.key,
    label: sc.label,
    reachable: s.reachable(sc.key),
  }));
  const serviceTone: "ok" | "error" | "pending" = s.healthError ? "error" : s.health ? "ok" : "pending";
  const serviceText = s.healthError
    ? `本地服务未连接：${s.healthError}`
    : s.health
      ? `本地服务已连接 · v${s.health.version} · schema ${s.health.schema_id}`
      : "正在检测本地服务…";

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar__brand">
          <h1>清洗工作台</h1>
          <span className="tagline">本地数据清洗 · 原文不出本机</span>
        </div>
        <WizardStepper steps={steps} current={s.screen} onJump={(k) => s.goTo(k as ScreenKey)} />
        <span className="topbar__spacer" />
        <Tooltip text={serviceText}>
          <span className="topbar__btn">
            <StatusDot tone={serviceTone} />
            <Badge tone={s.healthError ? "danger" : s.health ? "success" : "neutral"}>
              {s.healthError ? "服务离线" : s.health ? "服务在线" : "检测中"}
            </Badge>
          </span>
        </Tooltip>
        <button type="button" className="btn btn--ghost btn--sm" onClick={onOpenHistory}>
          运行历史
        </button>
        <button type="button" className="btn btn--ghost btn--sm" onClick={onOpenSettings}>
          设置 / 关于
        </button>
      </header>

      {(s.error || s.info) && (
        <div className="global-banner-slot">
          {s.error ? (
            <div className="banner banner--error" role="alert">
              <span className="banner__icon" aria-hidden>!</span>
              <span className="banner__text">{s.error}</span>
              <button className="banner__close" onClick={() => s.setError("")} aria-label="关闭错误提示">✕</button>
            </div>
          ) : (
            <div className="banner banner--info" role="status">
              <span className="banner__icon" aria-hidden>i</span>
              <span className="banner__text">{s.info}</span>
              <button className="banner__close" onClick={() => s.setInfo("")} aria-label="关闭提示">✕</button>
            </div>
          )}
        </div>
      )}

      <div className="screen-wrap">{children}</div>
    </div>
  );
}
