// SPDX-License-Identifier: Apache-2.0
/** 屏 4「配方」（向导流核心）：左「已选步骤」+ 右 320px「操作目录」+ 顶部影响范围条。
 *  每步用 deriveRecipe() 派生 pending/ready/unknown/risky 状态，
 *  待配置步骤显式标记并在页脚阻断生成配方，不再静默放过。
 *  操作目录条为真实组件 `components/OpCatalogRail.tsx`，行为等价、视觉不变。 */
import React from "react";
import { WizardFooter } from "../components/AppShell";
import { Button, EmptyState } from "../components/ui/primitives";
import { StepCard } from "../components/ui/stepcard";
import { OpCatalogRail } from "../components/OpCatalogRail";
import { levelLabel, riskFlagMatchesStep } from "../lib/ops";
import type { Level } from "../lib/ops";
import { Session } from "../hooks/useSession";

export function RecipeScreen({ s }: { s: Session }) {
  const pendingCount = s.derived.pendingIndexes.length;
  const riskCount = s.derived.riskyIndexes.length;
  const usedOps = new Set(s.picked.map((p) => p.op));

  return (
    <>
      <div className="screen screen--split">
        <div className="screen__main">
          <div className="screen-head">
            <h2 className="screen-q">第四步：排好清洗顺序</h2>
            <p className="screen-sub">每一步按顺序作用在上一步结果上；顺序即执行顺序，可上移 / 下移调整。</p>
          </div>

          <div className="summary-bar" role="status" aria-label="影响范围">
            <div className="summary-bar__item">
              <span className="summary-bar__label">已选步骤</span>
              <span className="summary-bar__value">{s.picked.length} 步</span>
            </div>
            <div className="summary-bar__item">
              <span className="summary-bar__label">待配置</span>
              <span className="summary-bar__value" style={{ color: pendingCount ? "var(--warning-600)" : undefined }}>
                {pendingCount} 步
              </span>
            </div>
            <div className="summary-bar__item">
              <span className="summary-bar__label">风险提示</span>
              <span className="summary-bar__value" style={{ color: riskCount ? "var(--danger-600)" : undefined }}>
                {riskCount} 项
              </span>
            </div>
            <div className="summary-bar__item">
              <span className="summary-bar__label">数据规模</span>
              <span className="summary-bar__value">
                {s.rowCount.toLocaleString("zh-CN")} 行 × {s.columns.length} 列
              </span>
            </div>
            <span className="summary-bar__spacer" />
            {s.picked.length > 0 && (
              <span className="summary-bar__actions">
                <Button size="sm" variant="ghost" onClick={s.resetOps}>清空步骤</Button>
              </span>
            )}
          </div>

          {s.picked.length === 0 ? (
            <section className="panel">
              <EmptyState
                icon="☰"
                title="还没有清洗步骤"
                desc={
                  s.eda
                    ? "从右侧操作目录挑选步骤，也可以回体检屏一键采纳建议步骤。"
                    : "从右侧操作目录挑选步骤，或先做一次体检拿建议。"
                }
                action={
                  <Button variant="secondary" onClick={() => s.goTo(s.eda ? "recipe" : "eda")}>
                    {s.eda ? "从建议开始" : "去体检拿建议"}
                  </Button>
                }
              />
            </section>
          ) : (
            <div className="recipe-steps">
              {s.picked.map((p, i) => (
                <StepCard
                  key={`${p.op}-${i}`}
                  index={i}
                  picked={p}
                  status={s.derived.statuses[i] ?? "unknown"}
                  columns={s.columns}
                  riskNote={
                    (s.plan?.risk_flags ?? []).find((f) => riskFlagMatchesStep(f, i)) ?? undefined
                  }
                  onChange={(key, value) => s.updateParam(i, key, value)}
                  onRemove={() => s.removeOp(i)}
                  onMoveUp={() => s.moveOp(i, -1)}
                  onMoveDown={() => s.moveOp(i, 1)}
                  canMoveUp={i > 0}
                  canMoveDown={i < s.picked.length - 1}
                />
              ))}
            </div>
          )}
        </div>

        <aside className="screen__rail">
          <OpCatalogRail onAdd={s.addOp} usedOps={usedOps} />
        </aside>
      </div>

      <WizardFooter
        hint={
          s.picked.length === 0
            ? "从右侧目录添加清洗步骤"
            : pendingCount > 0
              ? `还有 ${pendingCount} 步待配置，补齐必填参数才能生成配方`
              : riskCount > 0
                ? `有 ${riskCount} 步涉及高危操作，建议在确认屏复核`
                : "步骤顺序即执行顺序"
        }
      >
        <Button variant="secondary" onClick={() => s.goTo("eda")}>上一步：体检</Button>
        <Button
          variant="primary"
          disabled={s.picked.length === 0 || pendingCount > 0}
          loading={s.planBusy}
          onClick={() => void s.submitPlan()}
        >
          生成配方并进入确认
        </Button>
      </WizardFooter>
    </>
  );
}

export const RECIPE_LEVEL_LABEL = levelLabel as (l: Level) => string;
