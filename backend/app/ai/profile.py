# SPDX-License-Identifier: Apache-2.0
"""列形态画像 —— 只产出「形态标签 + 列级统计」，绝不携带原始单元格值（红线）。

形态标签是「确定性事实」：由本模块在本地算好后随请求下发；
模型据此推断语义类型与建议算子，但拿不到任何一个数据值。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from ..operations.data.currency_affixes import (CURRENCY_PREFIXES,
                                                CURRENCY_SUFFIXES,
                                                CURRENCY_UNIT_CONVERSIONS)
from .config import CELL_PROFILES

# ── 受控形态标签（23 项，清单唯一来源在 config，禁止模型自造）──
CELL_PROFILE_LABELS = CELL_PROFILES

PLACEHOLDERS = {"-", "--", "---", "—", "–", "N/A", "n/a", "NA", "null", "NULL", "None", "无", "未知", "待补"}

_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")
_ID18_RE = re.compile(r"^\d{17}[\dXx]$")
_PHONE_RE = re.compile(r"^(?:\+?86[- ]?)?1[3-9]\d{9}$|^0\d{2,3}[- ]?\d{7,8}$")
_DATETIME_RE = re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}[ T]\d{1,2}:\d{2}(:\d{2})?$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SLASH_DATE_RE = re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$|^\d{1,2}/\d{1,2}/\d{4}$")
_DOT_DATE_RE = re.compile(r"^\d{4}\.\d{1,2}\.\d{1,2}$|^\d{1,2}\.\d{1,2}\.\d{4}$")
_CN_DATE_RE = re.compile(r"^\d{4}年\d{1,2}月(\d{1,2}日?)?$")
_COMPACT_DATE_RE = re.compile(r"^\d{8}$")
_INT_RE = re.compile(r"^[+-]?\d+$")
_NUM_RE = re.compile(r"^[+-]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$")
_NUM_UNIT_RE = re.compile(r"^([+-]?[\d,]+(?:\.\d+)?)\s*([^\d\s]+)$")
# 货币前后缀**不在本文件另写一份**（货币词表唯一来源 = operations/data/currency_affixes.py）。
# 本模块只把那份表编译成正则，用于把单元格判成 CURRENCY_PREFIX / CURRENCY_SUFFIX 形态标签。
_CUR_SYMBOLS = "".join(p for p in CURRENCY_PREFIXES if not p.isascii())
_CUR_CODES = "|".join(sorted((p for p in CURRENCY_PREFIXES if p.isascii()), key=len, reverse=True))
# 量级倍率词同样取自该表换算对的键，避免在 AI 侧再抄一份单位词表
_CUR_MAGNITUDES = {u for pair in CURRENCY_UNIT_CONVERSIONS for u in pair}
_CUR_SUFFIX_RE_ALT = "|".join(sorted(set(CURRENCY_SUFFIXES) | _CUR_MAGNITUDES, key=len, reverse=True))
_CURRENCY_PREFIX_RE = re.compile(rf"^[{re.escape(_CUR_SYMBOLS)}]|^({_CUR_CODES})\b", re.IGNORECASE)
_CURRENCY_SUFFIX_RE = re.compile(rf"({_CUR_SUFFIX_RE_ALT})$", re.IGNORECASE)
_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-./#]{2,}$")
_CN_RE = re.compile(r"^[\u4e00-\u9fff]+$")
_LATIN_RE = re.compile(r"^[A-Za-z][A-Za-z\s'.,&()\-]*$")

# 计数单位 / 量词（与 operations/data/quantity_units.py 口径一致）
_COUNT_UNITS = {"件", "台", "个", "只", "条", "套", "箱", "包", "份", "批", "次", "人", "户", "笔", "项", "组", "pcs", "PCS"}


def _has_fullwidth(text: str) -> bool:
    for ch in text:
        cp = ord(ch)
        if 0xFF01 <= cp <= 0xFF5E or cp == 0x3000:
            return True
    return False


def classify_value(value: Any) -> str:
    """把单个单元格判成一个受控形态标签（空值 → EMPTY）。"""
    if value is None:
        return "EMPTY"
    raw = str(value)
    if raw.strip() == "":
        return "EMPTY"
    if raw != raw.strip():
        return "HAS_SPACE"
    v = raw.strip()

    if _has_fullwidth(v):
        return "FULLWIDTH"
    if v in PLACEHOLDERS:
        return "PLACEHOLDER_DASH"
    if _EMAIL_RE.match(v):
        return "EMAIL_SHAPE"
    if _ID18_RE.match(v):
        return "ID_SHAPE"
    if _PHONE_RE.match(v):
        return "PHONE_SHAPE"
    if _DATETIME_RE.match(v):
        return "DATETIME"
    if _CN_DATE_RE.match(v):
        return "DATE_NONSTD"
    if _ISO_DATE_RE.match(v):
        return "DATE_ISO"
    if _SLASH_DATE_RE.match(v):
        return "DATE_SLASH"
    if _DOT_DATE_RE.match(v):
        return "DATE_DOT"
    if _COMPACT_DATE_RE.match(v):
        return "DATE_NONSTD"

    if v.endswith("%") or v.endswith("％"):
        return "PERCENT"
    if _CURRENCY_PREFIX_RE.match(v):
        return "CURRENCY_PREFIX"
    if _CURRENCY_SUFFIX_RE.search(v):
        return "CURRENCY_SUFFIX"

    unit_match = _NUM_UNIT_RE.match(v)
    if unit_match:
        return "NUM+COUNT_UNIT" if unit_match.group(2) in _COUNT_UNITS else "NUM+OTHER_UNIT"

    if _INT_RE.match(v):
        return "INT"
    if _NUM_RE.match(v):
        return "DECIMAL"

    if " " in v or "\t" in v:
        return "HAS_SPACE"
    if _CN_RE.match(v):
        return "TEXT_CN"
    if _CODE_RE.match(v) and any(ch.isdigit() for ch in v):
        return "CODE_ALNUM"
    if _LATIN_RE.match(v):
        return "TEXT_LATIN"
    return "MIXED"


def _length_stats(values: List[str]) -> Dict[str, int]:
    lens = [len(v) for v in values if v.strip() != ""]
    if not lens:
        return {"length_min": 0, "length_max": 0}
    return {"length_min": min(lens), "length_max": max(lens)}


def cell_profile(column: str, values: List[Any]) -> Dict[str, Any]:
    """单列画像：只有列级统计与形态标签分布，不含任何原始值 / 样本原值。"""
    total = len(values)
    non_empty_values = [str(v) for v in values if v is not None and str(v).strip() != ""]
    dist: Dict[str, int] = {}
    for value in values:
        label = classify_value(value)
        dist[label] = dist.get(label, 0) + 1

    distribution = [
        {"profile": label, "count": count, "ratio": round(count / total, 4) if total else 0.0}
        for label, count in sorted(dist.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    stats = _length_stats([str(v) for v in values])
    return {
        "column": column,
        "total_count": total,
        "non_empty_count": len(non_empty_values),
        "non_empty_rate": round(len(non_empty_values) / total, 4) if total else 0.0,
        "unique_count": len({str(v) for v in non_empty_values}),
        "length_min": stats["length_min"],
        "length_max": stats["length_max"],
        "profile_distribution": distribution,
    }


def top_profile_evidence(profile: Dict[str, Any], top_n: int = 3) -> List[str]:
    """由形态分布生成 evidence 串（确定性事实，可直接展示给用户）。"""
    out = []
    for item in profile.get("profile_distribution", [])[:top_n]:
        if item["ratio"] <= 0:
            continue
        out.append(f'{item["profile"]} {round(item["ratio"] * 100)}%')
    return out


def build_column_profiles(columns: List[str], rows: List[List[Any]], max_rows: int = 5000) -> List[Dict[str, Any]]:
    """整表逐列画像（行数上限保护：超限只取前 max_rows 行统计）。"""
    sample_rows = rows[:max_rows] if max_rows and len(rows) > max_rows else rows
    profiles = []
    for idx, col in enumerate(columns):
        values = [row[idx] if idx < len(row) else None for row in sample_rows]
        profiles.append(cell_profile(col, values))
    return profiles
