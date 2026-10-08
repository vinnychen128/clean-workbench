// SPDX-License-Identifier: Apache-2.0
/** 配方屏「操作目录条」—— 真实组件名 OpCatalogRail（原 RecipeScreen 内联 `.rail` 抽出，
 *  行为等价、视觉不变：同样的分组、搜索、已选标记与点击加入）。
 *
 *  目录与后端注册表同源（`lib/ops.ts::OP_DIRECTORY`），搜索命中名称 / 操作名 / 说明。
 */
import React, { useMemo, useState } from "react";
import { LEVELS, OP_DIRECTORY } from "../lib/ops";
import { TextInput } from "./ui/primitives";

export interface OpCatalogRailProps {
  /** 点击目录项加入配方 */
  onAdd: (op: string) => void;
  /** 已在配方里出现的操作（打「已选」标记） */
  usedOps: Set<string>;
}

export function OpCatalogRail({ onAdd, usedOps }: OpCatalogRailProps) {
  const [kw, setKw] = useState("");

  const groups = useMemo(() => {
    const key = kw.trim().toLowerCase();
    return LEVELS.map((l) => ({
      level: l.value,
      label: l.label,
      ops: OP_DIRECTORY.filter(
        (o) =>
          o.level === l.value &&
          (!key ||
            o.name.toLowerCase().includes(key) ||
            o.op.toLowerCase().includes(key) ||
            o.desc.toLowerCase().includes(key)),
      ),
    })).filter((g) => g.ops.length > 0);
  }, [kw]);

  return (
    <div className="rail">
      <div className="rail__head">
        <span className="rail__title">操作目录</span>
        <span className="rail__item-desc" style={{ marginLeft: "auto" }}>
          共 {OP_DIRECTORY.length} 个
        </span>
      </div>
      <TextInput value={kw} onChange={setKw} placeholder="搜索操作名称…" ariaLabel="搜索操作" />

      {groups.length === 0 && <div className="rail__empty">没有匹配的操作，换个关键词试试。</div>}

      {groups.map((g) => (
        <div className="rail__group" key={g.level}>
          <div className="rail__group-title">{g.label}（{g.ops.length}）</div>
          {g.ops.map((o) => (
            <button
              type="button"
              className="rail__item"
              key={o.op}
              onClick={() => onAdd(o.op)}
              title={`${o.name}：${o.desc}`}
            >
              <span className="rail__item-name">
                {o.name}
                {usedOps.has(o.op) && <span className="badge badge--neutral" style={{ marginLeft: 6 }}>已选</span>}
              </span>
              <span className="rail__add" aria-hidden>＋</span>
              <span className="rail__item-desc">{o.desc}</span>
            </button>
          ))}
        </div>
      ))}

      <div className="rail__group">
        <div className="rail__group-title">说明</div>
        <div className="rail__item-desc">
          目录与后端注册表同源；不确定选哪个，可先到体检屏看建议。
        </div>
      </div>
    </div>
  );
}
