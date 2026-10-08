"""前后校验：清洗前后指标对比 + 目标达成判断。

指标维度：行数 / 列数 / 空值率 / 重复率（既有）＋ 洗后残留五键（
`amount_dirty_ratio` / `date_nonstandard_ratio` / `date_invalid_count` /
`unit_dirty_ratio` / `numeric_dirty_ratio`，判据与检测器同源，见 `verify/residual.py`）。
判定：既有目标阈值 + 五键 `target=0`（仅在体检命中该问题时纳入）+ 行数塌缩闸；
缺失数据不猜（无分数=low 不判通过）。

接口契约（前后端同版）：
- `metrics.<新键> = {"before": x, "after": y}`
- `unmet` 为**对象数组**：`[{key, before, after, rows, message}]`，`message` 形如
  `金额残留: 103 行（占比 17.4%）`；旧字符串形态不再保留。
- `passed = 五键全部达标（含 date_invalid_count == 0）` + 既有目标达标 + 无行数塌缩。
"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import residual


def _empty_ratio(rows: List[List[Any]]) -> float:
    if not rows:
        return 1.0
    total = sum(len(r) for r in rows)
    if total == 0:
        return 1.0
    empties = sum(1 for r in rows for c in r if c is None or (isinstance(c, str) and c.strip() == ""))
    return empties / total


def _dup_ratio(rows: List[List[Any]]) -> float:
    if not rows:
        return 1.0
    seen = set()
    dups = 0
    for r in rows:
        key = tuple(str(c) for c in r)
        if key in seen:
            dups += 1
        else:
            seen.add(key)
    return dups / len(rows)


def compare(before: Dict[str, Any], after: Dict[str, Any], targets: Optional[Dict[str, float]] = None,
            profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """前后对比。before/after 含 columns + rows；profile = 体检结果（决定五键是否纳入判定）。

    返回指标表 + 通过判定 + `unmet` 对象数组（契约）。
    """
    b_rows, a_rows = before["rows"], after["rows"]
    metrics: Dict[str, Any] = {
        "rows": {"before": len(b_rows), "after": len(a_rows)},
        "columns": {"before": len(before["columns"]), "after": len(after["columns"])},
        "empty_ratio": {"before": round(_empty_ratio(b_rows), 4), "after": round(_empty_ratio(a_rows), 4)},
        "dup_ratio": {"before": round(_dup_ratio(b_rows), 4), "after": round(_dup_ratio(a_rows), 4)},
    }
    targets = targets or {
        "empty_ratio": round(_empty_ratio(b_rows) + 0.05, 4),  # 相对目标：容忍清洗置空无效值带来的小幅上升
        "dup_ratio": 0.0,
    }
    passed = True
    unmet: List[Dict[str, Any]] = []
    for key, target in targets.items():
        if key not in metrics:
            continue
        after_v = metrics[key]["after"]
        if after_v > target:
            passed = False
            unmet.append({"key": key, "before": metrics[key]["before"], "after": after_v,
                          "rows": None, "message": f"{key}: {after_v} > {target}"})

    # --- 洗后残留五键（判据与检测器/操作同源；仅纳入体检命中过的问题）--------
    keys = residual.scope_keys(profile) if profile is not None else \
        residual.scope_keys_from_data(before["columns"], b_rows)
    unit_cols = residual.unit_scope_columns(before["columns"], b_rows) \
        if residual.NUMERIC_DIRTY_RATIO in keys else None
    b_meas = residual.measure(before["columns"], b_rows, keys, unit_cols)
    a_meas = residual.measure(after["columns"], a_rows, keys, unit_cols)
    for key in sorted(keys):
        metrics[key] = {"before": b_meas[key]["value"], "after": a_meas[key]["value"]}
        if a_meas[key]["value"] > 0:
            passed = False
            unmet.append(residual.unmet_entry(key, b_meas[key], a_meas[key]))

    # 行数显著塌缩（>30% 减少）视为可疑，不判通过
    if b_rows and len(a_rows) < 0.7 * len(b_rows):
        passed = False
        unmet.append({"key": "row_collapse", "before": len(b_rows), "after": len(a_rows),
                      "rows": len(b_rows) - len(a_rows),
                      "message": f"行数大幅减少: {len(b_rows)} → {len(a_rows)}"})
    return {"metrics": metrics, "passed": passed, "unmet": unmet}
