"""体检样本抽取（契约）：`profile.issues[i].samples = [{row, column, value}]`（≤20 条，脱敏后）。

为什么放在后端（已定死走这条）：
① 前端按行号回索引原始数据，在"列被清洗后行号错位"时会给出**错值**（比没有更糟）；
② 样本脱敏只能在后端做（红线：数据不出本机、不泄露原始敏感值）。

抽值规则：优先取该问题"真正脏的那个单元格"（按问题类型给判据），取不到则退回该行第一个非空单元格。
"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Sequence

from ..operations.data.currency_affixes import is_canonical_amount, looks_like_amount, to_halfwidth
from ..operations.impl.cell_ops import CellDateNormalizeOp

MAX_SAMPLES = 20
MAX_VALUE_CHARS = 60

# 长数字串（手机号/身份证/银行卡/订单号）中段打码：保留前 3 后 2
_LONG_DIGITS = re.compile(r"\d{7,}")
# 乱码判据（与 mojibake 检测器同口径的宽松版：常见拉丁扩展乱码片段 / 替换字符）
_MOJIBAKE = re.compile(r"[\u00c0-\u00ff]{2,}|\ufffd|\u00e4\u00b8")


def mask_value(value: Any) -> Any:
    """脱敏 + 截断：长数字串中段打码，超长文本截断（样本只用于"看见问题长什么样"）。"""
    if value is None:
        return None
    text = str(value)
    if not text.strip():
        return text

    def _mask(match: re.Match) -> str:
        digits = match.group(0)
        if len(digits) <= 6:
            return digits
        return f"{digits[:3]}{'*' * (len(digits) - 5)}{digits[-2:]}"

    text = _LONG_DIGITS.sub(_mask, text)
    if len(text) > MAX_VALUE_CHARS:
        text = text[:MAX_VALUE_CHARS] + "…"
    return text


def _is_null(cell: Any) -> bool:
    return cell is None or (isinstance(cell, str) and cell.strip() == "")


def _is_amount_dirty(cell: Any) -> bool:
    return isinstance(cell, str) and cell.strip() != "" and looks_like_amount(cell) and not is_canonical_amount(cell)


def _is_date_dirty(cell: Any) -> bool:
    if not isinstance(cell, str):
        return False
    text = to_halfwidth(cell).strip()
    return bool(text and CellDateNormalizeOp._DATE_SHAPE.match(text))


def _is_unit_dirty(cell: Any) -> bool:
    if not isinstance(cell, str):
        return False
    text = cell.strip()
    return bool(text) and bool(re.match(r"^[+-]?\d+(?:\.\d+)?\s*[^\d\s.]", text))


def _is_format_dirty(cell: Any) -> bool:
    if not isinstance(cell, str) or cell.strip() == "":
        return False
    return bool(cell != cell.strip() or re.search(r"[\uFF00-\uFFEF]", cell))


def _is_identifier_dirty(cell: Any) -> bool:
    return isinstance(cell, str) and cell.strip() != "" and bool(re.search(r"[^0-9A-Za-z_-]", cell.strip()))


def _is_mojibake(cell: Any) -> bool:
    return isinstance(cell, str) and bool(_MOJIBAKE.search(cell))


# 问题类型 → 该问题"真正脏"的判据（取样本用），取不到则退回首个非空单元格
DIRTY_PREDICATES: Dict[str, Callable[[Any], bool]] = {
    "null": _is_null,
    "amount": _is_amount_dirty,
    "date": _is_date_dirty,
    "unit": _is_unit_dirty,
    "format": _is_format_dirty,
    "identifier_column": _is_identifier_dirty,
    "mojibake": _is_mojibake,
    "outlier": lambda cell: isinstance(cell, str) and cell.strip() != "",
}

# 整行类问题（无"某个单元格"可指）→ 取整行前若干格拼串
ROW_LEVEL_ISSUES = ("duplicate",)


def _sample_for_row(columns: Sequence[str], row: Sequence[Any], issue_name: str,
                    prefer_columns: Sequence[str] = ()) -> Dict[str, Any]:
    predicate = DIRTY_PREDICATES.get(issue_name)
    order = [i for i, name in enumerate(columns) if name in set(prefer_columns)]
    order += [i for i in range(len(columns)) if i not in set(order)]
    if issue_name in ROW_LEVEL_ISSUES:
        cells = [str(c) for c in row[:4] if c not in (None, "")]
        return {"column": None, "value": mask_value("、".join(cells))}
    for ci in order:
        cell = row[ci] if ci < len(row) else None
        if predicate is not None and predicate(cell):
            return {"column": columns[ci] if ci < len(columns) else None, "value": mask_value(cell)}
    for ci in order:
        cell = row[ci] if ci < len(row) else None
        if not _is_null(cell):
            return {"column": columns[ci] if ci < len(columns) else None, "value": mask_value(cell)}
    return {"column": None, "value": None}


def build_samples(columns: Sequence[str], rows: Sequence[Sequence[Any]],
                  issue: Dict[str, Any]) -> List[Dict[str, Any]]:
    """按体检问题的命中行号抽 ≤20 条样本（值已脱敏）。"""
    name = issue.get("issue_name", "")
    prefer = issue.get("columns") or ([issue["column"]] if issue.get("column") else [])
    row_ids = list(issue.get("rows") or [])[:MAX_SAMPLES]
    samples: List[Dict[str, Any]] = []
    for rid in row_ids:
        row = rows[rid] if 0 <= rid < len(rows) else None
        if row is None:
            continue
        item = _sample_for_row(columns, row, name, prefer)
        item["row"] = rid
        samples.append({"row": item["row"], "column": item["column"], "value": item["value"]})
    return samples


def enrich_profile(profile: Dict[str, Any], columns: Sequence[str],
                   rows: Sequence[Sequence[Any]]) -> Dict[str, Any]:
    """就地给 profile 的每个问题补 `samples`（只增字段，不改既有字段）。"""
    for issue in (profile or {}).get("issues") or []:
        sample = build_samples(columns, rows, issue)
        if sample:
            issue["samples"] = sample
    return profile
