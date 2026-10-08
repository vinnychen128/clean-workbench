// SPDX-License-Identifier: Apache-2.0
/** 步骤卡：配方中单步的展示 + 就地配置 + 排序/删除。
 *  待配置步骤以虚线「待配置」chip + 左侧警示边框显式标记，
 *  必填缺失时直接在字段下给出内联错误并禁用上移/下移以外的危险操作（不阻断整表阅读）。 */
import React from "react";
import { ChipMulti, IconButton, Select, TextInput } from "./primitives";
import { StatusChip } from "./feedback";
import {
  OpField,
  OpSpec,
  STEP_STATUS_LABEL,
  StepStatus,
  isBlank,
  opSummary,
  specOf,
} from "../../lib/ops";

function FieldRenderer({
  field,
  spec,
  value,
  columns,
  invalid,
  onChange,
}: {
  field: OpField;
  spec: OpSpec;
  value: unknown;
  columns: string[];
  invalid: boolean;
  onChange: (v: unknown) => void;
}) {
  const label = (
    <span className="field__label">
      {field.label}
      {field.required && <em className="req"> *</em>}
    </span>
  );
  const err = invalid ? <span className="field__error">此项必填</span> : null;

  if (field.type === "multi") {
    return (
      <div className={`field${invalid ? " field--invalid" : ""}`}>
        {label}
        <ChipMulti
          options={columns}
          value={Array.isArray(value) ? (value as string[]) : []}
          onChange={(v) => onChange(v)}
          ariaLabel={`${field.label}`}
        />
        {err}
      </div>
    );
  }

  if (field.type === "select") {
    const options =
      field.options ??
      (field.source === "columns" ? columns.map((c) => ({ value: c, label: c })) : []);
    return (
      <div className={`field${invalid ? " field--invalid" : ""}`}>
        {label}
        <Select
          value={typeof value === "string" ? value : ""}
          onChange={(v) => onChange(v)}
          options={options}
          ariaLabel={field.label}
          invalid={invalid}
        />
        {err}
      </div>
    );
  }

  return (
    <div className={`field${invalid ? " field--invalid" : ""}`}>
      {label}
      <TextInput
        type={field.type === "number" ? "number" : "text"}
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(v) => onChange(v)}
        placeholder={field.placeholder}
        ariaLabel={field.label}
        invalid={invalid}
      />
      {err}
    </div>
  );
}

export function StepCard({
  index,
  picked,
  status,
  columns,
  riskNote,
  onChange,
  onRemove,
  onMoveUp,
  onMoveDown,
  canMoveUp,
  canMoveDown,
}: {
  index: number;
  picked: { op: string; params: Record<string, unknown> };
  status: StepStatus;
  columns: string[];
  riskNote?: string;
  onChange: (key: string, value: unknown) => void;
  onRemove: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  canMoveUp: boolean;
  canMoveDown: boolean;
}) {
  const spec = specOf(picked.op);
  const missing = new Set(
    (spec?.fields ?? [])
      .filter((f) => {
        const required =
          f.required || (f.source === "columns" && f.defaultValue === undefined && f.type !== "text" && f.type !== "number");
        return required && isBlank(picked.params[f.key]);
      })
      .map((f) => f.key),
  );

  return (
    <div
      className={`step-card${status === "pending" ? " is-pending" : ""}${status === "risky" ? " is-risky" : ""}`}
    >
      <div className="step-card__idx" aria-hidden>{index + 1}</div>
      <div className="step-card__body">
        <div className="step-card__head">
          <span className="step-card__title">{spec ? spec.name : picked.op}</span>
          <span className="step-card__badges">
            <StatusChip status={status} label={STEP_STATUS_LABEL[status]} />
          </span>
          <span className="step-card__spacer" />
          <span className="step-card__actions">
            <IconButton label="上移" onClick={onMoveUp} disabled={!canMoveUp}>↑</IconButton>
            <IconButton label="下移" onClick={onMoveDown} disabled={!canMoveDown}>↓</IconButton>
            <IconButton label="删除该步" onClick={onRemove} danger>✕</IconButton>
          </span>
        </div>
        <div className="step-card__note">{spec ? spec.desc : `未知操作 ${picked.op}`}</div>
        {status === "pending" && (
          <div className="step-card__note">
            待配置：还有 {missing.size} 项必填参数未选择，补齐后才能生成配方。
          </div>
        )}
        {status === "risky" && riskNote && <div className="step-card__note">{riskNote}</div>}
        <div className="step-card__fields">
          {(spec?.fields ?? []).map((f) => (
            <FieldRenderer
              key={f.key}
              field={f}
              spec={spec!}
              value={picked.params[f.key]}
              columns={columns}
              invalid={missing.has(f.key)}
              onChange={(v) => onChange(f.key, v)}
            />
          ))}
        </div>
        <div className="step-card__note">当前参数：{opSummary(picked)}</div>
      </div>
    </div>
  );
}
