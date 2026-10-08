"""单元格级操作（单元格级 8 项）。"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from dateutil import parser as dateutil_parser

from ..base import OpContext, OpResult, Operation
from ..data.currency_affixes import CURRENCY_UNIT_CONVERSIONS, clean_amount, to_halfwidth
# 剥离模式的量词判据来自单一来源词表（同一判据只写一份）—— 不得在本文件再写第二份
from ..data.quantity_units import is_count_unit

_FULLWIDTH_MAP = {ord(c): ord(c) - 0xFEE0 for c in "！＂＃＄％＆＇（）＊＋，－．／：；＜＝＞？＠［＼］＾＿｀｛｜｝～"}
_FULLWIDTH_MAP.update({ord("　"): ord(" "), ord("０"): ord("0"), ord("１"): ord("1"), ord("２"): ord("2"),
                       ord("３"): ord("3"), ord("４"): ord("4"), ord("５"): ord("5"), ord("６"): ord("6"),
                       ord("７"): ord("7"), ord("８"): ord("8"), ord("９"): ord("9"),
                       ord("Ａ"): ord("A"), ord("Ｂ"): ord("B"), ord("Ｃ"): ord("C"), ord("Ｄ"): ord("D"),
                       ord("Ｅ"): ord("E"), ord("Ｆ"): ord("F"), ord("Ｇ"): ord("G"), ord("Ｈ"): ord("H"),
                       ord("Ｉ"): ord("I"), ord("Ｊ"): ord("J"), ord("Ｋ"): ord("K"), ord("Ｌ"): ord("L"),
                       ord("Ｍ"): ord("M"), ord("Ｎ"): ord("N"), ord("Ｏ"): ord("O"), ord("Ｐ"): ord("P"),
                       ord("Ｑ"): ord("Q"), ord("Ｒ"): ord("R"), ord("Ｓ"): ord("S"), ord("Ｔ"): ord("T"),
                       ord("Ｕ"): ord("U"), ord("Ｖ"): ord("V"), ord("Ｗ"): ord("W"), ord("Ｘ"): ord("X"),
                       ord("Ｙ"): ord("Y"), ord("Ｚ"): ord("Z")})
# 全角小写字母 ａ-ｚ（U+FF41–U+FF5A）：与上表同规则补齐。
# 修复：此前仅映射全角大写与数字，导致 "Ｔｅｓｔ" 只转首字母（现已覆盖全角字母全表）。
_FULLWIDTH_MAP.update({0xFF41 + i: ord("a") + i for i in range(26)})


def _cell(row: List[Any], ci: int):
    return row[ci] if ci < len(row) else None


def _set_cell(row: List[Any], ci: int, v: Any) -> None:
    while len(row) <= ci:
        row.append(None)
    row[ci] = v


class CellTrimOp(Operation):
    op_name = "cell_trim"
    level = "cell"
    description = "去空格：去除单元格首尾空白（可选去除内部多余空白）"

    def validate(self, ctx: OpContext) -> List[str]:
        cols = [c for c in (ctx.params.get("columns") or [ctx.params.get("column")]) if c]
        if not cols:
            return ["未选择目标列"]
        return [f"缺少列: {c}" for c in cols if c not in ctx.columns]

    def apply(self, ctx: OpContext) -> OpResult:
        cols = ctx.params.get("columns") or [ctx.params.get("column")]
        idxs = [ctx.columns.index(c) for c in cols if c]
        affected = 0
        for row in ctx.rows:
            for ci in idxs:
                v = _cell(row, ci)
                if isinstance(v, str) and v != v.strip():
                    _set_cell(row, ci, v.strip())
                    affected += 1
        return OpResult(rows=ctx.rows, columns=ctx.columns, log={"op": self.op_name, "rows_affected": affected})

    def describe(self, params: Dict[str, Any]) -> str:
        return f"去除列 {params.get('columns') or params.get('column')} 首尾空格"


class CellFullwidthOp(Operation):
    op_name = "cell_fullwidth"
    level = "cell"
    description = "全角半角：将全角字符转半角（数字 / 字母 / 标点）"

    def validate(self, ctx: OpContext) -> List[str]:
        cols = [c for c in (ctx.params.get("columns") or [ctx.params.get("column")]) if c]
        if not cols:
            return ["未选择目标列"]
        return [f"缺少列: {c}" for c in cols if c not in ctx.columns]

    def apply(self, ctx: OpContext) -> OpResult:
        cols = ctx.params.get("columns") or [ctx.params.get("column")]
        idxs = [ctx.columns.index(c) for c in cols if c]
        affected = 0
        for row in ctx.rows:
            for ci in idxs:
                v = _cell(row, ci)
                if isinstance(v, str):
                    nv = v.translate(_FULLWIDTH_MAP)
                    if nv != v:
                        _set_cell(row, ci, nv)
                        affected += 1
        return OpResult(rows=ctx.rows, columns=ctx.columns, log={"op": self.op_name, "rows_affected": affected})

    def describe(self, params: Dict[str, Any]) -> str:
        return f"列 {params.get('columns') or params.get('column')} 全角转半角"


class CellUnitConvertOp(Operation):
    op_name = "cell_unit_convert"
    level = "cell"
    description = ("单位换算：数值列单位转换（内置常用换算表；未知单位不猜、标记）；"
                   "另支持「剥离单位」模式，把 `3件` 这类数字+量词粘连值洗成纯数值")

    _CONVERSIONS = {
        ("MPa", "bar"): 10.0, ("bar", "MPa"): 0.1, ("MPa", "kPa"): 1000.0, ("kPa", "MPa"): 0.001,
        ("m", "cm"): 100.0, ("cm", "m"): 0.01, ("m", "mm"): 1000.0, ("mm", "m"): 0.001,
        ("cm", "mm"): 10.0, ("mm", "cm"): 0.1, ("kg", "g"): 1000.0, ("g", "kg"): 0.001,
        ("kg", "t"): 0.001, ("t", "kg"): 1000.0, ("L", "ml"): 1000.0, ("ml", "L"): 0.001,
        ("℃", "°C"): 1.0, ("°C", "℃"): 1.0,
    }
    # 货币换算对来自符号表单一来源常量（货币词不得在别处再写一份）
    _CONVERSIONS.update(CURRENCY_UNIT_CONVERSIONS)

    # 「剥离单位」模式的目标值白名单：仅当 to 显式取这些值之一才触发，
    # 留空/其他值一律走原有换算逻辑，保证既有行为不回归（「不改既有算子行为」）
    _STRIP_TARGETS = frozenset({"纯数值", "数值", "number", "numeric"})
    # 前导数值 + 后缀：`3件` → ("3", "件")、`100 件` → ("100", "件")、`12.5` → ("12.5", "")；
    # 非数字开头（如 `N/A`）不匹配。
    # 后缀**整词**命中计数单位词表（`operations/data/quantity_units.py` 单一来源）才剥离；
    # 物理量、货币等非计数单位后缀一律保留原值并计入 `skipped_non_count`，禁止静默改写。
    _STRIP_SPLIT = re.compile(r"^([+-]?\d+(?:\.\d+)?)\s*(.*)$")
    # 非计数单位后缀的披露文案（describe / log 共用一份措辞）
    _NON_COUNT_NOTE = "非计数单位后缀（如 kg / 货币符号）保留原值，未剥离"

    @staticmethod
    def _norm_target(to: Any) -> str:
        return str(to).strip() if to is not None else ""

    def _is_strip(self, to: Any) -> bool:
        return self._norm_target(to) in self._STRIP_TARGETS

    def validate(self, ctx: OpContext) -> List[str]:
        col = ctx.params.get("column")
        if not col:
            return ["未选择目标列"]
        if col not in ctx.columns:
            return [f"缺少列: {col}"]
        frm, to = ctx.params.get("from"), ctx.params.get("to")
        if self._is_strip(to):
            # 剥离单位模式：只取数值，不做换算，故**不查换算表**
            # （修复「数量列 `3件` 建议走本算子却零效果」：量词之间本无换算对，此前被 validate 卡住）
            return []
        if frm == to:
            # 同单位 = 恒等换算。原实现直接查表报错，导致"选下拉默认值提交即失败"（联动缺口）
            return []
        if (frm, to) not in self._CONVERSIONS:
            # 错误文案须写清原因与可用换算范围，不得只丢一句"不支持的单位换算"
            available = "、".join(f"{a}→{b}" for a, b in sorted(self._CONVERSIONS))
            return [f"不支持的单位换算: {frm} → {to}（该单位对不在内置换算表内）。可用换算: {available}"]
        return []

    def apply(self, ctx: OpContext) -> OpResult:
        col = ctx.params["column"]
        ci = ctx.columns.index(col)
        frm, to = ctx.params.get("from"), ctx.params.get("to")
        strip = self._is_strip(to)
        # 非剥离路径保持原行为（含「不在换算表即 KeyError」的语义，由 validate 前置拦截）
        factor = 1.0 if (strip or frm == to) else self._CONVERSIONS[(frm, to)]
        affected = 0
        skipped_non_count = 0
        skipped_non_samples: List[str] = []
        for row in ctx.rows:
            v = _cell(row, ci)
            if strip:
                # 剥离单位：取前导数值（`3件` → 3、`100 件` → 100、`12.5` → 12.5）。
                # 非字符串（已是数值）与取不到数值的值一律跳过，不误改。
                if not isinstance(v, str):
                    continue
                m = self._STRIP_SPLIT.match(v.strip().replace(",", ""))
                if not m:
                    continue
                suffix = m.group(2).strip()
                # 后缀非量词（物理量 / 货币等非计数单位后缀）时剥离会篡改数值语义，
                # 一律**保留原值**并计数披露（不阻断整列、也不静默）。
                if suffix and not is_count_unit(suffix):
                    skipped_non_count += 1
                    if len(skipped_non_samples) < 10:
                        skipped_non_samples.append(v)
                    continue
                num = float(m.group(1))
                _set_cell(row, ci, int(num) if num.is_integer() else num)
                affected += 1
                continue
            try:
                num = float(str(v).replace(",", "").replace(frm, "").strip()) if isinstance(v, str) else float(v)
            except (ValueError, TypeError):
                continue
            _set_cell(row, ci, round(num * factor, 6))
            affected += 1
        return OpResult(rows=ctx.rows, columns=ctx.columns,
                        log={"op": self.op_name, "rows_affected": affected,
                             "mode": "strip" if strip else "convert",
                             # 被守卫拦下的非计数单位值（保留原值）如实计数，报告侧据此披露
                             "skipped_non_count": skipped_non_count,
                             "skipped_non_samples": skipped_non_samples,
                             "skipped_non_reason": self._NON_COUNT_NOTE if skipped_non_count else ""})

    def describe(self, params: Dict[str, Any]) -> str:
        frm, to = params.get("from"), params.get("to")
        if self._is_strip(to):
            src = f"剥离「{frm}」后缀" if frm else "剥离单位后缀"
            # 剥离只对计数单位（量词）成立，非量词后缀会保留原值并披露 —— 描述里先讲清口径
            return f"列 {params.get('column')} {src} → 纯数值（仅计数单位如「件/台」；{self._NON_COUNT_NOTE}）"
        tail = "" if frm != to else "（同单位，恒等换算）"
        return f"列 {params.get('column')} 单位换算 {frm} → {to}{tail}"


class CellCaseOp(Operation):
    op_name = "cell_case"
    level = "cell"
    description = "大小写：文本转大写 / 小写 / 首字母大写"

    def validate(self, ctx: OpContext) -> List[str]:
        cols = [c for c in (ctx.params.get("columns") or [ctx.params.get("column")]) if c]
        if not cols:
            return ["未选择目标列"]
        return [f"缺少列: {c}" for c in cols if c not in ctx.columns]

    def apply(self, ctx: OpContext) -> OpResult:
        cols = ctx.params.get("columns") or [ctx.params.get("column")]
        idxs = [ctx.columns.index(c) for c in cols if c]
        mode = ctx.params.get("mode", "upper")
        affected = 0
        for row in ctx.rows:
            for ci in idxs:
                v = _cell(row, ci)
                if isinstance(v, str):
                    nv = {"upper": v.upper(), "lower": v.lower(), "title": v.title()}.get(mode, v)
                    if nv != v:
                        _set_cell(row, ci, nv)
                        affected += 1
        return OpResult(rows=ctx.rows, columns=ctx.columns, log={"op": self.op_name, "rows_affected": affected})

    def describe(self, params: Dict[str, Any]) -> str:
        return f"列 {params.get('columns') or params.get('column')} 大小写 {params.get('mode', 'upper')}"


class CellDateNormalizeOp(Operation):
    op_name = "cell_date_normalize"
    level = "cell"
    description = "日期规范化：多格式日期统一为 YYYY-MM-DD（支持 YYYYMMDD / 分隔符 / 中文年月日；非法日期保留原值并登记未处理）"

    # 日期形态门禁：只有"看起来是日期"的值才进入解析，避免把普通文本误判为日期
    _DATE_SHAPE = re.compile(
        r"^(?:\d{8}"
        r"|\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"
        r"|\d{4}年\d{1,2}月\d{1,2}日"
        r")(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?$"
    )

    def validate(self, ctx: OpContext) -> List[str]:
        col = ctx.params.get("column")
        if not col:
            return ["未选择目标列"]
        return [] if col in ctx.columns else [f"缺少列: {col}"]

    @classmethod
    def _parse_date(cls, s: str) -> Optional[Any]:
        """用 dateutil 统一解析（不再维护手写格式清单）。非法年月日返回 None。"""
        text = s.replace("年", "-").replace("月", "-").replace("日", "")
        text = re.sub(r"\s+", " ", text).strip().split(" ")[0]
        try:
            dt = dateutil_parser.parse(text, fuzzy=False)
        except (ValueError, OverflowError, TypeError):
            return None
        if not (1900 <= dt.year <= 2100):  # 解析器"猜"出来的越界年份一律不认
            return None
        return dt

    def apply(self, ctx: OpContext) -> OpResult:
        col = ctx.params["column"]
        ci = ctx.columns.index(col)
        affected = 0
        sample_before = None
        unresolved: List[str] = []
        for row in ctx.rows:
            v = _cell(row, ci)
            if not isinstance(v, str):
                continue
            s = to_halfwidth(v).strip()
            if s == "" or not self._DATE_SHAPE.match(s):
                continue
            dt = self._parse_date(s)
            if dt is None:
                unresolved.append(v)  # 非法日期：保留原值 + 登记未处理（不得静默丢弃）
                continue
            normalized = dt.strftime("%Y-%m-%d")
            if normalized != v:  # 已是 YYYY-MM-DD 的快路径天然命中此处
                sample_before = sample_before or v
                _set_cell(row, ci, normalized)
                affected += 1
        log: Dict[str, Any] = {"op": self.op_name, "rows_affected": affected, "sample_before": sample_before}
        if unresolved:
            log["unresolved_count"] = len(unresolved)
            log["unresolved_samples"] = unresolved[:5]
            log["unresolved_reason"] = "日期非法/无法识别（保留原值）"
        return OpResult(rows=ctx.rows, columns=ctx.columns, log=log)

    def describe(self, params: Dict[str, Any]) -> str:
        return f"列 {params.get('column')} 日期规范化 → YYYY-MM-DD（非日期格式与非法日期保留原值）"


class CellAmountCleanOp(Operation):
    op_name = "cell_amount_clean"
    level = "cell"
    description = ("金额清洗：去空白 / 全角转半角 / 去除货币前缀与后缀（前后缀可叠加；"
                   "支持的币种与符号清单为单一来源，见 operations/data/currency_affixes.py）"
                   "/ 去千分位 / 括号负数转负号，统一为纯数字；无法解析的值保留原值并登记未处理")

    def validate(self, ctx: OpContext) -> List[str]:
        col = ctx.params.get("column")
        if not col:
            return ["未选择目标列"]
        return [] if col in ctx.columns else [f"缺少列: {col}"]

    def apply(self, ctx: OpContext) -> OpResult:
        col = ctx.params["column"]
        ci = ctx.columns.index(col)
        affected = 0
        unresolved: List[str] = []
        for row in ctx.rows:
            v = _cell(row, ci)
            if not isinstance(v, str) or v.strip() == "":
                continue
            cleaned = clean_amount(v)
            if cleaned is None:
                unresolved.append(v)  # 无法解析：保留原值 + 登记未处理（不得静默置空）
                continue
            if cleaned != v:
                _set_cell(row, ci, cleaned)
                affected += 1
        log: Dict[str, Any] = {"op": self.op_name, "rows_affected": affected}
        if unresolved:
            log["unresolved_count"] = len(unresolved)
            log["unresolved_samples"] = unresolved[:5]
            log["unresolved_reason"] = "无法解析为金额（保留原值）"
        return OpResult(rows=ctx.rows, columns=ctx.columns, log=log)

    def describe(self, params: Dict[str, Any]) -> str:
        return f"列 {params.get('column')} 金额清洗（去货币前后缀/千分位/全角，统一纯数字）"


class CellTextReplaceOp(Operation):
    op_name = "cell_text_replace"
    level = "cell"
    description = "文本替换：整词 / 正则替换"

    def validate(self, ctx: OpContext) -> List[str]:
        cols = [c for c in (ctx.params.get("columns") or [ctx.params.get("column")]) if c]
        if not cols:
            return ["未选择目标列"]
        return [f"缺少列: {c}" for c in cols if c not in ctx.columns]

    def apply(self, ctx: OpContext) -> OpResult:
        cols = ctx.params.get("columns") or [ctx.params.get("column")]
        idxs = [ctx.columns.index(c) for c in cols if c]
        old, new = ctx.params.get("old", ""), ctx.params.get("new", "")
        regex = ctx.params.get("regex", False)
        affected = 0
        for row in ctx.rows:
            for ci in idxs:
                v = _cell(row, ci)
                if not isinstance(v, str) or old == "":
                    continue
                nv = re.sub(old, new, v) if regex else v.replace(old, new)
                if nv != v:
                    _set_cell(row, ci, nv)
                    affected += 1
        return OpResult(rows=ctx.rows, columns=ctx.columns, log={"op": self.op_name, "rows_affected": affected})

    def describe(self, params: Dict[str, Any]) -> str:
        return f"列 {params.get('columns') or params.get('column')} 文本替换 {params.get('old')!r} → {params.get('new')!r}"


class CellFillMissingOp(Operation):
    op_name = "cell_fill_missing"
    level = "cell"
    description = "缺失值填充：按常量 / 前值 / 后值 / 列均值填充空值"

    def validate(self, ctx: OpContext) -> List[str]:
        col = ctx.params.get("column")
        if not col:
            return ["未选择目标列"]
        return [] if col in ctx.columns else [f"缺少列: {col}"]

    def apply(self, ctx: OpContext) -> OpResult:
        col = ctx.params["column"]
        ci = ctx.columns.index(col)
        method = ctx.params.get("method", "constant")
        const = ctx.params.get("value")
        affected = 0
        # 均值预计算
        if method == "mean":
            vals = []
            for row in ctx.rows:
                v = _cell(row, ci)
                try:
                    vals.append(float(str(v).replace(",", "")) if isinstance(v, str) else float(v))
                except (ValueError, TypeError):
                    continue
            mean = round(sum(vals) / len(vals), 4) if vals else None
            const = mean
        last = None
        for row in ctx.rows:
            v = _cell(row, ci)
            if v is None or (isinstance(v, str) and v.strip() == ""):
                fill = const if method == "constant" else last
                if fill is not None:
                    _set_cell(row, ci, fill)
                    affected += 1
            else:
                last = v
        # 后值回填（method=next）
        if method == "next":
            next_val = None
            for row in reversed(ctx.rows):
                v = _cell(row, ci)
                if v is None or (isinstance(v, str) and v.strip() == ""):
                    if next_val is not None:
                        _set_cell(row, ci, next_val)
                        affected += 1
                else:
                    next_val = v
        return OpResult(rows=ctx.rows, columns=ctx.columns, log={"op": self.op_name, "rows_affected": affected})

    def describe(self, params: Dict[str, Any]) -> str:
        return f"列 {params.get('column')} 缺失值填充（{params.get('method', 'constant')}）"
