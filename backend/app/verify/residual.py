"""洗后残留指标：检测器 ←→ 洗后指标一一对应，**判据与检测器同一份**。

五个指标键名定死（不得改名、不得任选；均为新增键，不覆盖既有 rows/columns/empty_ratio/dup_ratio）：

| 键 | 含义 | 值 |
|---|---|---|
| `amount_dirty_ratio` | 金额列残留非规范值 | 命中行数 / 总行数 |
| `date_nonstandard_ratio` | 日期列残留"可解析但非 ISO"值 | 命中行数 / 总行数 |
| `date_invalid_count` | 语义非法日期行数（不可清洗） | **绝对行数** |
| `unit_dirty_ratio` | 单位残留 / 混用（物理量单位混用、未知单位、计数单位粘连）| 命中行数 / 总行数 |
| `numeric_dirty_ratio` | 数量列非数值残留 | 命中行数 / 总行数 |

口径要点：
- 阈值一律 `target = 0`；**只在"该问题在体检中命中过"时才纳入判定**（未命中不判）。
- 判据同源：金额用 `currency_affixes.looks_like_amount/is_canonical_amount`，日期用
  `CellDateNormalizeOp._DATE_SHAPE/_parse_date`（**语义解析，不只看形态**），
  单位用 `UnitDetector`（体检命中 → 配方覆盖 → 洗后指标三者同一份判据）。
- 不重复计数：金额残留只进 `amount_dirty_ratio`；`unit_dirty_ratio` 认单位类问题
  （货币形态的值在 UnitDetector 内已被排除）；`numeric_dirty_ratio` 只统计**体检时 unit 命中的列**
  （物理量混用列 + 计数单位/量词粘连列，列集取"洗前"，前后同列集才可比）。
- 扫描范围与检测器一致＝全表所有单元格（检测器不按列限定，故指标也不按列限定）。
"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set

from ..detectors.base import DetectorRegistry
from ..detectors.impl.unit import UnitDetector
from ..operations.data.currency_affixes import PLAIN_NUMBER, is_canonical_amount, looks_like_amount, to_halfwidth
from ..operations.impl.cell_ops import CellDateNormalizeOp

AMOUNT_DIRTY_RATIO = "amount_dirty_ratio"
DATE_NONSTANDARD_RATIO = "date_nonstandard_ratio"
DATE_INVALID_COUNT = "date_invalid_count"
UNIT_DIRTY_RATIO = "unit_dirty_ratio"
NUMERIC_DIRTY_RATIO = "numeric_dirty_ratio"

ALL_KEYS = (AMOUNT_DIRTY_RATIO, DATE_NONSTANDARD_RATIO, DATE_INVALID_COUNT, UNIT_DIRTY_RATIO, NUMERIC_DIRTY_RATIO)

# 指标 → 中文名（unmet 的 message 与报告未处理项共用）
KEY_LABELS = {
    AMOUNT_DIRTY_RATIO: "金额残留",
    DATE_NONSTANDARD_RATIO: "日期非标准格式残留",
    DATE_INVALID_COUNT: "日期非法（不可清洗）",
    UNIT_DIRTY_RATIO: "单位残留/混用",
    NUMERIC_DIRTY_RATIO: "数量非数值残留",
}

# 检测器 issue_name → 由此派生的指标键（一一对应）
ISSUE_TO_KEYS = {
    "amount": (AMOUNT_DIRTY_RATIO,),
    "date": (DATE_NONSTANDARD_RATIO, DATE_INVALID_COUNT),
    "unit": (UNIT_DIRTY_RATIO, NUMERIC_DIRTY_RATIO),
}

# 绝对数口径的键（其余为比例）
COUNT_KEYS = (DATE_INVALID_COUNT,)


def issue_hit(issue: Any) -> bool:
    """该体检项是否命中（有行号 / rows_total>0 / 分数>0 任一即算命中）。"""
    if not isinstance(issue, dict):
        return False
    name = issue.get("issue_name")
    rows = issue.get("rows") or []
    total = issue.get("rows_total")
    if total is None:
        total = len(rows)
    score = issue.get(f"{name}_score")
    if score is None:
        score = issue.get("score")
    return bool(total) or bool(rows) or bool(score)


def scope_keys(profile: Optional[Dict[str, Any]]) -> Set[str]:
    """由体检结果派生需要纳入判定的指标键（未命中不判）。"""
    keys: Set[str] = set()
    for issue in (profile or {}).get("issues") or []:
        if not issue_hit(issue):
            continue
        keys.update(ISSUE_TO_KEYS.get(issue.get("issue_name"), ()))
    return keys


def scope_keys_from_data(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> Set[str]:
    """没有体检结果时（直连 compare / smoke）就地跑检测器派生同一份判定范围。"""
    return scope_keys(DetectorRegistry.run_all(list(columns), [list(r) for r in rows]))


def unit_scope_columns(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> List[str]:
    """洗前 unit 检测命中的列（numeric_dirty_ratio 的统计范围）：物理量混用 / 未知单位 / 计数单位粘连。"""
    report = UnitDetector().compute(list(columns), [list(r) for r in rows])
    return [str(c) for c in (report.get("columns") or []) if c]


# --- 单元格判据（与检测器/操作实现同源） --------------------------------------

def _amount_dirty(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != "" and looks_like_amount(value) and not is_canonical_amount(value)


def _date_state(value: Any) -> Optional[str]:
    """返回 None（不是日期形态/已是 ISO）/ 'nonstandard' / 'invalid'。"""
    if not isinstance(value, str):
        return None
    s = to_halfwidth(value).strip()
    if s == "" or not CellDateNormalizeOp._DATE_SHAPE.match(s):
        return None
    dt = CellDateNormalizeOp._parse_date(s)
    if dt is None:
        return "invalid"
    return None if dt.strftime("%Y-%m-%d") == s else "nonstandard"


def _non_numeric(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    s = value.strip()
    if s == "":
        return False
    return not PLAIN_NUMBER.match(s)


def _row_hits(rows: Sequence[Sequence[Any]], check: Callable[[Any], bool],
              only_cols: Optional[Set[int]] = None) -> List[int]:
    hits: List[int] = []
    for i, row in enumerate(rows):
        for ci, cell in enumerate(row):
            if only_cols is not None and ci not in only_cols:
                continue
            if check(cell):
                hits.append(i)
                break
    return hits


def measure(columns: Sequence[str], rows: Sequence[Sequence[Any]], keys: Iterable[str],
            unit_cols: Optional[Sequence[str]] = None) -> Dict[str, Dict[str, Any]]:
    """按 keys 统计洗后残留。返回 {键: {value, rows, rows_total}}（不含的键就不返回）。"""
    keys = set(keys)
    rows = [list(r) for r in rows]
    total = len(rows)
    out: Dict[str, Dict[str, Any]] = {}

    def put(key: str, hits: List[int], ratio: bool = True) -> None:
        value = round(len(hits) / total, 4) if (ratio and total) else (0.0 if ratio else len(hits))
        out[key] = {"value": value, "rows": len(hits), "rows_total": total}

    if AMOUNT_DIRTY_RATIO in keys:
        put(AMOUNT_DIRTY_RATIO, _row_hits(rows, _amount_dirty))

    if DATE_NONSTANDARD_RATIO in keys or DATE_INVALID_COUNT in keys:
        states = {key: [] for key in (DATE_NONSTANDARD_RATIO, DATE_INVALID_COUNT)}
        want = {DATE_NONSTANDARD_RATIO: "nonstandard", DATE_INVALID_COUNT: "invalid"}
        for key, state in want.items():
            if key in keys:
                states[key] = _row_hits(rows, lambda cell, _s=state: _date_state(cell) == _s)
        if DATE_NONSTANDARD_RATIO in keys:
            put(DATE_NONSTANDARD_RATIO, states[DATE_NONSTANDARD_RATIO])
        if DATE_INVALID_COUNT in keys:
            put(DATE_INVALID_COUNT, states[DATE_INVALID_COUNT], ratio=False)

    if UNIT_DIRTY_RATIO in keys:
        report = UnitDetector().compute(list(columns), rows)
        hits = int(report.get("rows_total") or 0)
        out[UNIT_DIRTY_RATIO] = {"value": round(hits / total, 4) if total else 0.0, "rows": hits, "rows_total": total}

    if NUMERIC_DIRTY_RATIO in keys:
        only = {i for i, name in enumerate(columns) if name in set(unit_cols or ())}
        put(NUMERIC_DIRTY_RATIO, _row_hits(rows, _non_numeric, only if unit_cols else None))

    return out


def unmet_entry(key: str, before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """契约：unmet 明细项 = {key, before, after, rows, message}。"""
    label = KEY_LABELS.get(key, key)
    rows = int(after.get("rows") or 0)
    if key in COUNT_KEYS:
        message = f"{label}: {rows} 行"
    else:
        pct = f"{(after.get('value') or 0) * 100:.1f}%"
        message = f"{label}: {rows} 行（占比 {pct}）"
    return {"key": key, "before": before.get("value"), "after": after.get("value"),
            "rows": rows, "message": message}
