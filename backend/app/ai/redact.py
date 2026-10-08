# SPDX-License-Identifier: Apache-2.0
"""脱敏规则 —— 仅 `redacted_samples` 档使用（红线的最后一道防线）。

默认 `shape_only` 档根本不走到这里；只有用户显式开启采样值分享时，
才允许经本模块脱敏后的样本外发。**无法确定形态的值一律丢弃**（fail-closed）。
"""
from __future__ import annotations

import re
from typing import Any, List, Optional

_EMAIL_RE = re.compile(r"^([^@\s]+)@([^@\s]+\.[A-Za-z]{2,})$")
_MOBILE_RE = re.compile(r"^1\d{10}$")
_IDCARD_RE = re.compile(r"^\d{17}[\dXx]$")
_DIGITS_RE = re.compile(r"^\d{11,}$")
_ADDR_PROV_RE = re.compile(r"^[\u4e00-\u9fff]{2,4}(省|自治区|特别行政区)")
_ADDR_CITY_RE = re.compile(r"[\u4e00-\u9fff]{2,6}(市|自治州|地区|盟)")
_ADDR_ANY_RE = re.compile(r"(省|市|区|县|镇|乡|村|路|街|巷|号|栋|室|单元)")
_CN_NAME_RE = re.compile(r"^[\u4e00-\u9fff]{2,4}$")


def redact_value(value: Any) -> Optional[str]:
    """
    返回脱敏后的可外发文本；无法安全脱敏时返回 None（调用方必须丢弃该样本）。

    规则（均需单测）：
    - 手机 `1XXXXXXXXXX`（保留位数）
    - 邮箱 `a***@***.com`
    - 身份证前后各留 1 位其余 `*`
    - 连续数字 ≥11 位 → 位数标签 `LEN_18`
    - 姓名 首字 + `*`
    - 地址 → 只留行政区级，其余丢弃
    - 卡号账号 → 只留后 4 位
    - 无法确定 → 丢弃该值
    """
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None

    # 邮箱：a***@***.com
    m = _EMAIL_RE.match(text)
    if m:
        local, domain = m.group(1), m.group(2)
        tld = domain.rsplit(".", 1)[-1]
        return f"{local[0]}***@***.{tld}"

    # 手机：1 + 十个掩码位（保留位数）
    if _MOBILE_RE.match(text):
        return text[0] + "*" * 10

    # 身份证：前后各留 1 位
    if _IDCARD_RE.match(text):
        return text[0] + "*" * (len(text) - 2) + text[-1]

    # 卡号 / 账号（16~19 位纯数字）：只留后 4 位
    if text.isdigit() and 16 <= len(text) <= 19:
        return "*" * (len(text) - 4) + text[-4:]

    # 其余连续数字 ≥11 位：位数标签
    if _DIGITS_RE.match(text):
        return f"LEN_{len(text)}"

    # 地址：只留行政区级
    if _ADDR_ANY_RE.search(text) and len(text) >= 4:
        parts = []
        prov = _ADDR_PROV_RE.match(text)
        if prov:
            parts.append(prov.group(0))
        city = _ADDR_CITY_RE.search(text)
        if city:
            parts.append(city.group(0))
        return ("".join(parts) + "***") if parts else "***"

    # 姓名：首字 + *
    if _CN_NAME_RE.match(text):
        return text[0] + "*"

    # 无法确定 → 丢弃
    return None


def redact_samples(values: List[Any], limit: int = 5) -> List[str]:
    """逐个脱敏，丢弃无法安全脱敏的项，最多返回 limit 条。"""
    out: List[str] = []
    for value in values:
        if len(out) >= limit:
            break
        safe = redact_value(value)
        if safe is not None:
            out.append(safe)
    return out
