"""金额符号表与金额文本归一（交付物）。

设计要点：
- **单一事实来源**：检测器（`AmountDetector`）与操作（`CellAmountCleanOp`）共用本表的符号常量与
  归一函数，保证"体检命中 → 配方覆盖 → 洗后指标"三者判据一致。
- **可配置**：新增币种 / 后缀只需改本文件常量，无须改动操作与检测器代码。

归一顺序（对齐口径）：去空格 → 全角转半角 → 去前/后缀 → 去千分位 → 括号负数 → 校验。
"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

# --- 可配置符号表 ---------------------------------------------------------
# 货币前缀：中文币称 + 符号 + 英文代码（匹配大小写不敏感；NFKC 归一后 `￥` 会变成 `¥`，两者都需保留）
# 长前缀须排在前面，避免 "人民币" 被短代码截断
CURRENCY_PREFIXES = ("人民币", "RMB", "CNY", "USD", "EUR", "JPY", "HKD", "GBP",
                     "¥", "￥", "$", "€", "£", "₩")
# 货币后缀：仅收纳"剥离后不改变数值大小"的币种标记。
# 刻意**不含** 万元 / 角 / 分——它们是量级或子单位（1万元=10000、50分=0.5元），
# 直接剥离会把 "1万元" 错洗成 "1"，属于静默篡改数值；这类值一律保留原值并登记未处理。
CURRENCY_SUFFIXES = ("人民币", "元", "RMB", "CNY", "USD", "EUR")

# 规范金额形态：可选正负号 + 可选货币符号 + 千分位整数 + 至多两位小数（检测器判定"是否规范"用）
CANONICAL_AMOUNT = re.compile(r"^[+-]?[$￥¥]?\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?$")

# --- 货币量级换算（单一来源的延伸）--------------------------------
# 货币单位与符号只在本文件出现（grep 证据：别处不得再写一份 元/万元/USD/RMB/¥/$/€ 词表）。
# `cell_unit_convert` 的货币换算对（元 ↔ 万元）从本表取，避免在操作实现里硬编码货币词。
CURRENCY_UNIT_CONVERSIONS = {
    ("元", "万元"): 0.0001,
    ("万元", "元"): 10000.0,
}
# 清洗后应满足的纯数值形态（不含任何非 [0-9.\-] 字符）
PLAIN_NUMBER = re.compile(r"^[+-]?\d+(?:\.\d+)?$")

# 非金额形态：日期 / 手机号 / 编号——它们的问题归属 date / format 检测器，不得计为金额缺口
_DATE_LIKE = re.compile(r"^(?:\d{8}|\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{4}年\d{1,2}月\d{1,2}日)$")
_PHONE_LIKE = re.compile(r"^\+?\d[\d\-\s()]{5,}$")


def to_halfwidth(text: str) -> str:
    """全角 → 半角（NFKC 归一，覆盖全角数字 / 标点 / 空格）。"""
    return unicodedata.normalize("NFKC", str(text))


def normalize_amount_text(text: Any) -> str:
    """把金额文本归一为待解析的数值串（不做合法性判断）。

    例：``1,299.00元`` → ``1299.00``；``RMB 4055.14`` → ``4055.14``；``(1200)`` → ``-1200``。
    """
    s = to_halfwidth(text).strip()
    s = re.sub(r"\s+", "", s)
    neg = False
    if len(s) > 2 and s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    # 前 / 后缀可叠加（如 "￥100 元"），循环剥净
    changed = True
    while changed and s:
        changed = False
        for prefix in CURRENCY_PREFIXES:
            if s.upper().startswith(prefix.upper()):
                s = s[len(prefix):]
                changed = True
                break
        for suffix in CURRENCY_SUFFIXES:
            if s.upper().endswith(suffix.upper()):
                s = s[: len(s) - len(suffix)]
                changed = True
                break
    if "," in s:
        # 只接受合法千分位分组（1,200 / 12,345,678.90）；"1,2,3" 这类不猜、不洗，原样交回判定为不可解析
        if not re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", s):
            return s
        s = s.replace(",", "")
    return f"-{s}" if neg else s


def format_normalized_amount(normalized: str) -> str:
    """按归一后的数值串写回（对齐小数位口径）。

    - 含小数点 → 固定两位小数（``1299.00`` → ``1299.00``、``1299.5`` → ``1299.50``）
    - 整数 → 整数串（``1200`` → ``1200``、``-1200`` → ``-1200``）
    """
    if "." in normalized:
        return f"{float(normalized):.2f}"
    return normalized[1:] if normalized.startswith("+") else normalized


def clean_amount(text: Any) -> Optional[str]:
    """一步清洗：返回可写回的金额串；不合规返回 ``None``。

    调用方拿到 ``None`` 时必须**保留原值**并登记未处理，不得静默置空。
    """
    normalized = normalize_amount_text(text)
    if not PLAIN_NUMBER.match(normalized):
        return None
    return format_normalized_amount(normalized)


def parse_amount(text: Any) -> Optional[float]:
    """解析金额文本为数值；不合规返回 ``None``。"""
    normalized = normalize_amount_text(text)
    if not PLAIN_NUMBER.match(normalized):
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def looks_like_amount(text: Any) -> bool:
    """是否按"金额口径"纳入判定（含货币前后缀 / 千分位 / 全角数字）。

    日期与手机号形态直接排除——旧实现用 `[,\\-]` 做守卫，导致日期 `2024-01-18`、手机号
    `138-5907-3635` 被计成"金额不规范"（联动修正）。
    """
    if not isinstance(text, str):
        return False
    raw = text.strip()
    if not raw or not re.search(r"\d", raw):
        return False
    s = to_halfwidth(raw)
    if _DATE_LIKE.match(s) or _PHONE_LIKE.match(s):
        return False
    if re.search(r"[￥¥$€£₩]", s):
        return True
    if re.match(r"^(?:RMB|CNY|USD|EUR|JPY|HKD|GBP)", s, re.I):
        return True
    if re.search(r"(?:元|万元|角|分|人民币)$", s):
        return True
    if "," in s:
        return True
    return bool(re.search(r"[０-９]", raw))


def is_canonical_amount(text: Any) -> bool:
    """是否为规范金额形态；非规范 = 检测器命中。

    注意：**不做全角归一**——全角数字 ``３５８.９４`` 属于"格式不规范"，必须能报出来。
    非字符串视为规范（不参与判定）。
    """
    if not isinstance(text, str):
        return True
    return bool(CANONICAL_AMOUNT.match(text.strip()))
