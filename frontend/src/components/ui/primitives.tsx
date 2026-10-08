// SPDX-License-Identifier: Apache-2.0
/** 基础原子件：无业务语义的通用控件与格式化工具。
 *  皮肤在 styles/components.css。 */
import React, { useEffect, useRef, useState } from "react";

/* ---------------- 骨架屏 ---------------- */

export function Skeleton({
  w = "100%",
  h = 12,
  r = 8,
  style,
}: {
  w?: number | string;
  h?: number | string;
  r?: number;
  style?: React.CSSProperties;
}) {
  return <span className="skeleton" style={{ width: w, height: h, borderRadius: r, ...style }} aria-hidden />;
}

export function SkeletonBlock({ rows = 4, title = true }: { rows?: number; title?: boolean }) {
  return (
    <div className="skeleton-block" aria-busy="true" aria-live="polite">
      {title && <Skeleton w={180} h={18} />}
      {Array.from({ length: rows }).map((_, i) => (
        <div className="skeleton-row" key={i}>
          <Skeleton w={`${92 - i * 6}%`} h={14} />
        </div>
      ))}
    </div>
  );
}

/* ---------------- 空态 ---------------- */

export function EmptyState({
  icon = "◎",
  title,
  desc,
  action,
}: {
  icon?: React.ReactNode;
  title: string;
  desc?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-state__icon" aria-hidden>{icon}</div>
      <div className="empty-state__title">{title}</div>
      {desc && <div className="empty-state__desc">{desc}</div>}
      {action && <div className="empty-state__action">{action}</div>}
    </div>
  );
}

/* ---------------- 徽章 ---------------- */

export type BadgeTone = "neutral" | "primary" | "success" | "warning" | "danger" | "info";

export function Badge({ tone = "neutral", children }: { tone?: BadgeTone; children: React.ReactNode }) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}

export function severityBadge(sev: string): BadgeTone {
  if (sev === "high") return "danger";
  if (sev === "medium") return "warning";
  if (sev === "low") return "info";
  return "neutral";
}

export const SEVERITY_LABEL: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
};

/* ---------------- 状态点 + 悬浮提示 ---------------- */

export type StatusTone = "ok" | "warn" | "error" | "pending" | "running";

export function StatusDot({ tone = "pending" }: { tone?: StatusTone }) {
  return <span className={`status-dot status-dot--${tone}`} aria-hidden />;
}

/** 键盘可达的悬浮说明（focus 亦可弹出）。 */
export function Tooltip({ text, children }: { text: React.ReactNode; children: React.ReactNode }) {
  return (
    <span className="tip" tabIndex={0}>
      {children}
      <span className="tip__bubble" role="tooltip">{text}</span>
    </span>
  );
}

/* ---------------- 按钮 ---------------- */

export function Button({
  variant = "secondary",
  size = "md",
  disabled,
  loading,
  onClick,
  children,
  className = "",
  ariaLabel,
  type = "button",
  title,
}: {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  disabled?: boolean;
  loading?: boolean;
  onClick?: () => void;
  children: React.ReactNode;
  className?: string;
  ariaLabel?: string;
  type?: "button" | "submit";
  title?: string;
}) {
  return (
    <button
      type={type}
      className={`btn btn--${variant} btn--${size} ${className}`.trim()}
      disabled={disabled || loading}
      onClick={onClick}
      aria-label={ariaLabel}
      aria-busy={loading || undefined}
      title={title}
    >
      {loading && <span className="btn__spinner" aria-hidden />}
      {children}
    </button>
  );
}

export function IconButton({
  label,
  onClick,
  disabled,
  danger,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className={`icon-btn${danger ? " icon-btn--danger" : ""}`}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

/* ---------------- 表单 ---------------- */

export function Select({
  value,
  onChange,
  options,
  disabled,
  ariaLabel,
  invalid,
  placeholder = "请选择…",
}: {
  value: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label: string }>;
  disabled?: boolean;
  ariaLabel?: string;
  invalid?: boolean;
  placeholder?: string;
}) {
  return (
    <select
      className="input"
      value={value ?? ""}
      aria-label={ariaLabel}
      aria-invalid={invalid || undefined}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">{placeholder}</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function TextInput({
  value,
  onChange,
  placeholder,
  disabled,
  ariaLabel,
  invalid,
  type = "text",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  disabled?: boolean;
  ariaLabel?: string;
  invalid?: boolean;
  type?: "text" | "number" | "search";
}) {
  return (
    <input
      className="input"
      type={type}
      value={value ?? ""}
      placeholder={placeholder}
      aria-label={ariaLabel}
      aria-invalid={invalid || undefined}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

/** 多选 chips：options 支持字符串数组或 {value,label} 数组。 */
export function ChipMulti({
  options,
  value,
  onChange,
  disabled,
  max,
  ariaLabel,
}: {
  options: Array<string | { value: string; label: string }>;
  value: string[];
  onChange: (v: string[]) => void;
  disabled?: boolean;
  max?: number;
  ariaLabel?: string;
}) {
  const opts = options.map((o) => (typeof o === "string" ? { value: o, label: o } : o));
  const selected = value ?? [];
  const toggle = (v: string) => {
    if (selected.includes(v)) onChange(selected.filter((x) => x !== v));
    else if (max && selected.length >= max) return;
    else onChange([...selected, v]);
  };
  if (!opts.length) return <span className="chips__empty">无可用选项</span>;
  return (
    <div className="chips" role="group" aria-label={ariaLabel}>
      {opts.map((o) => {
        const on = selected.includes(o.value);
        return (
          <button
            key={o.value}
            type="button"
            className={`chip${on ? " is-on" : ""}`}
            aria-pressed={on}
            disabled={disabled}
            onClick={() => toggle(o.value)}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/* ---------------- 折叠面板 ---------------- */

export function Collapse({
  title,
  meta,
  children,
  defaultOpen = false,
  tone,
  onToggle,
}: {
  title: React.ReactNode;
  meta?: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
  tone?: "warning" | "danger";
  /** 折叠态变化回调（AI 区块用「点开才请求」，未点开不得发起调用）。 */
  onToggle?: (open: boolean) => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={`collapse${open ? " is-open" : ""}`}>
      <button
        type="button"
        className="collapse__head"
        aria-expanded={open}
        onClick={() => {
          const next = !open;
          setOpen(next);
          onToggle?.(next);
        }}
      >
        <span className="collapse__caret" aria-hidden>▾</span>
        <span className="collapse__title">{title}</span>
        {meta && <span className="collapse__meta">{meta}</span>}
      </button>
      {open && <div className="collapse__body">{children}</div>}
    </div>
  );
}

/* ---------------- 渐进列表（大数据量不卡：前 N 条 + 展开更多） ---------------- */

/** 长清单分批渲染的取值钩子（前 N 条 + 展开更多 / 显示全部）。
 *  表格里用它能自己渲染成合法 `<tr>`，非表格区可直接用 ProgressiveList。 */
export function useProgressive<T>(items: T[], initial = 50, step = 200) {
  const [limit, setLimit] = useState(initial);
  const total = items.length;
  const shown = items.slice(0, limit);
  return {
    shown,
    total,
    shownCount: shown.length,
    hasMore: total > limit,
    expand: () => setLimit((n) => n + step),
    expandAll: () => setLimit(total),
    moreLabel: `展开更多（已显示 ${shown.length} / ${total}）`,
    hint: "为保持流畅，长清单按「前 N 条 + 展开更多」分批渲染。",
  };
}

/** 长清单只渲染前 N 条，其余按「展开更多 / 显示全部」分页铺开，
 *  避免一次性把几百行 DOM 全铺出来（问题清单 / 结果清单 / 未处理项共用本件）。
 *  注意：请勿把本件的按钮块直接放进 `<table><tbody>`（会渲染出非法的 div），
 *  表格内请改用 useProgressive 自行渲染成 `<tr>`。 */
export function ProgressiveList<T>({
  items,
  initial = 50,
  step = 200,
  renderItem,
  getKey,
  emptyText,
}: {
  items: T[];
  initial?: number;
  step?: number;
  renderItem: (item: T, index: number) => React.ReactNode;
  getKey?: (item: T, index: number) => React.Key;
  emptyText?: React.ReactNode;
}) {
  const p = useProgressive(items, initial, step);
  if (items.length === 0 && emptyText !== undefined) {
    return <div className="muted">{emptyText}</div>;
  }
  return (
    <>
      {p.shown.map((item, i) => (
        <React.Fragment key={getKey ? getKey(item, i) : i}>{renderItem(item, i)}</React.Fragment>
      ))}
      {p.hasMore && (
        <div className="toolbar" style={{ marginTop: "var(--space-2)", marginBottom: 0 }}>
          <Button size="sm" variant="secondary" onClick={p.expand}>
            {p.moreLabel}
          </Button>
          <Button size="sm" variant="ghost" onClick={p.expandAll}>
            显示全部
          </Button>
          <span className="muted">{p.hint}</span>
        </div>
      )}
    </>
  );
}

/* ---------------- 抽屉外壳 ---------------- */

export function DrawerShell({
  title,
  onClose,
  children,
  narrow,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  narrow?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    /* Esc 关闭 + Tab 焦点不逃逸（在抽屉内循环），focus-visible 由皮肤保证。 */
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const root = ref.current;
      if (!root) return;
      const focusables = root.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusables.length === 0) {
        e.preventDefault();
        root.focus();
        return;
      }
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement as HTMLElement | null;
      const inside = !!active && root.contains(active);
      if (e.shiftKey && (!inside || active === first)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (!inside || active === last)) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="drawer" role="dialog" aria-modal="true" aria-label={title}>
      <div className="drawer__backdrop" onClick={onClose} />
      <div className={`drawer__panel${narrow ? " drawer__panel--narrow" : ""}`} ref={ref} tabIndex={-1}>
        <div className="drawer__head">
          <h3 className="drawer__title">{title}</h3>
          <IconButton label="关闭" onClick={onClose}>✕</IconButton>
        </div>
        {children}
      </div>
    </div>
  );
}

/* ---------------- 格式化与下载 ---------------- */

export function fmtNum(n: unknown): string {
  if (typeof n === "number" && Number.isFinite(n)) {
    if (Number.isInteger(n)) return n.toLocaleString("zh-CN");
    return n.toLocaleString("zh-CN", { maximumFractionDigits: 4 });
  }
  if (typeof n === "string" && n !== "") {
    const asNum = Number(n);
    if (Number.isFinite(asNum) && /^-?\d+(\.\d+)?$/.test(n.trim())) return fmtNum(asNum);
    return n;
  }
  if (n === null || n === undefined || n === "") return "—";
  return String(n);
}

export function formatBytes(n: number): string {
  if (!Number.isFinite(n)) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

export function formatClock(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (x: number) => String(x).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** 下载纯文本（浏览器本地，不落服务端）。 */
export function downloadText(filename: string, text: string, mime = "text/plain;charset=utf-8") {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function downloadJson(filename: string, obj: unknown) {
  downloadText(filename, JSON.stringify(obj, null, 2), "application/json;charset=utf-8");
}

/* ---------------- 轮询 ---------------- */

export function useInterval(cb: () => void, ms: number | null) {
  const saved = useRef(cb);
  useEffect(() => {
    saved.current = cb;
  }, [cb]);
  useEffect(() => {
    if (ms === null) return;
    const id = window.setInterval(() => saved.current(), ms);
    return () => window.clearInterval(id);
  }, [ms]);
}
