#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""洗后脏点对账脚本 —— 交付前固定动作（已收编入仓，接 smoke / CI）。

用法:
    python3 scripts/check_residual_dirt.py <源文件.csv> <洗后文件.csv>

作用:按"脏点模式"统计 洗前 / 洗后 各多少行,输出对照表。
退出码:0 = 可清洗脏点(金额/日期/数量)洗后均为 0;1 = 仍有残留(不合格);2 = 用法错(参数个数不对 / 文件读不到)。

口径（日期段必须语义解析，分三类计数）:
  ① 可转的格式非标准（修完应为 0）—— 形态与语义都合法、只是写法不规范（2024/05/06、20240808、2024年5月6日）。
  ② 语义非法（转不了，不可清洗）—— 形态像日期但日期不存在（2024-13-99、2024.02.30）:
     只报告、标"待核对",**不计入不合格**,但必须出现在清洗报告的"未处理项"里。
     ⇒ 这类行从 ① 的各分项计数中**排除**,否则同一行被两类重复计数,
       产品侧正确修复(保留非法原值 + 登记未处理)之后脚本仍永远红。
  ③ 单位类(未知单位 / 物理量单位混用) —— 由「数量」组的「数字与单位粘连」「非数值残留」两项承担;
     脚本**不复制**产品侧单位词表(避免第二份词表,见单一来源)。

说明:脚本只读文件,不改数据;列名按表头关键词自动识别(金额/价/amount、日期/date、数量/件数/qty)。
基线:交付版 `核查脚本_洗后脏点对账.py`(md5 090328331f14688bb1622eaea6bd0322)已原样入仓,
     其后仅按升级「日期段语义解析 + 三类分桶」(见文件末「升级说明」)。
"""
from __future__ import annotations

import csv
import os
import re
import sys
from datetime import date as _date

FULLWIDTH_DIGITS = "０１２３４５６７８９"

# 日期形态（与产品侧 CellDateNormalizeOp._DATE_SHAPE 同口径:基础格式 / 分隔符 / 中文年月日）
_DATE_SHAPE = re.compile(
    r"^(?:\d{8}"
    r"|\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"
    r"|\d{4}年\d{1,2}月\d{1,2}日"
    r")$"
)


def _to_numbers(text: str) -> str:
    """中文年月日 → 横线分隔,便于统一做语义判定。"""
    return text.strip().replace("年", "-").replace("月", "-").replace("日", "")


def _semantic_state(text: str) -> str:
    """日期语义分类:'invalid' 语义非法 / 'nonstandard' 可转的非标准 / 'iso' / 'none' 不参与。"""
    t = str(text).strip()
    if not t or not _DATE_SHAPE.match(t):
        return "none"
    raw = _to_numbers(t)
    digits = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", raw)
    if digits:
        y, m, d = (int(g) for g in digits.groups())
    else:
        parts = re.split(r"[-/.]", raw)
        if len(parts) != 3:
            return "invalid"
        try:
            y, m, d = (int(p) for p in parts)
        except ValueError:
            return "invalid"
    try:
        _date(y, m, d)
    except ValueError:
        return "invalid"
    return "iso" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t) else "nonstandard"


def _semantic_bad_date(text: str) -> bool:
    """形态像日期但日期不存在,如 2024-13-99 / 2024.02.30 / 20240230。"""
    return _semantic_state(text) == "invalid"


# 各列的脏点模式:名称 -> 正则或谓词(命中即算脏)
# 约定:名称以「语义非法」开头的模式 = 不可清洗项,只报告、不计入不合格(须进报告"未处理项")
PATTERNS = {
    "金额": {
        "货币符号(￥/¥/$/€)": re.compile(r"[￥¥$€]"),
        "中文货币后缀(元/角/分/万元)": re.compile(r"[元角分]|万元"),
        "英文货币前后缀(RMB/CNY/USD)": re.compile(r"(RMB|CNY|USD|EUR)", re.IGNORECASE),
        "千分位逗号": re.compile(r"\d[,，]\d{3}"),
        "首尾空格": re.compile(r"^\s+|\s+$"),
        "全角字符/全角数字": re.compile(r"[\uFF00-\uFFEF]|[" + FULLWIDTH_DIGITS + r"]"),
        "非数值残留(清洗后应为空)": re.compile(r"[^0-9.\-]"),
    },
    "日期": {
        "中文日期": re.compile(r"年.{0,2}月"),
        "点/斜杠分隔": re.compile(r"\d{4}[./]\d{1,2}[./]\d{1,2}"),
        "基础格式 YYYYMMDD": re.compile(r"^\d{8}$"),
        "非标准格式(清洗后应为空)": re.compile(r"^(?!\d{4}-\d{2}-\d{2}$).+$"),
        "语义非法(日期不存在,不可清洗)": _semantic_bad_date,
    },
    "数量": {
        "数字与单位粘连": re.compile(r"^\s*[+-]?\d+(\.\d+)?\s*[^\d\s.]"),
        "非数值残留(清洗后应为空)": re.compile(r"[^0-9.\-]"),
    },
}

COLUMN_HINTS = {
    "金额": ("金额", "价格", "单价", "amount", "price", "money"),
    "日期": ("日期", "时间", "date", "time"),
    "数量": ("数量", "件数", "qty", "quantity", "count"),
}


def pick_column(header: list[str], kind: str) -> str | None:
    for hint in COLUMN_HINTS[kind]:
        for col in header:
            if hint in col.lower():
                return col
    return None


def read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def count_rows(rows: list[dict], col: str | None, pattern, exclude_indexes: set | None = None) -> int:
    """统计命中行数;exclude_indexes 内的行不计(语义非法行不重复计入"应清零"分项)。"""
    if not col:
        return 0
    exclude = exclude_indexes or set()
    hits = 0
    for i, row in enumerate(rows):
        if i in exclude:
            continue
        value = row.get(col)
        if value is None:
            continue
        text = str(value)
        if text.strip() == "":
            continue
        hit = pattern(text) if callable(pattern) else bool(pattern.search(text))
        if hit:
            hits += 1
    return hits


def _semantic_bad_indexes(rows: list[dict], col: str | None) -> set:
    """语义非法(日期不存在)行号集合 —— 从"应清零"分项里排除,单独走"待核对"。"""
    if not col:
        return set()
    return {i for i, r in enumerate(rows) if _semantic_bad_date(r.get(col) or "")}


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src_path, out_path = sys.argv[1], sys.argv[2]
    for path in (src_path, out_path):
        if not os.path.isfile(path):
            print(f"读不到文件:{path}")
            return 2
    src_rows, out_rows = read_csv(src_path), read_csv(out_path)
    if not src_rows:
        print(f"读不到数据:{src_path}")
        return 2

    header = list(src_rows[0].keys())
    cols = {kind: pick_column(header, kind) for kind in PATTERNS}
    print(f"源文件  : {src_path}  ({len(src_rows)} 行)")
    print(f"洗后文件: {out_path}  ({len(out_rows)} 行)")
    print(f"识别到的列: " + ", ".join(f"{k}={v or '未找到'}" for k, v in cols.items()))
    print()
    print(f"{'列':<5}{'脏点模式':<30}{'洗前':>7}{'洗后':>7}   结论")
    print("-" * 72)

    # 日期段先分桶,语义非法行从其余日期分项中排除(避免重复计数、避免脚本永远转不绿)
    bad_src = _semantic_bad_indexes(src_rows, cols["日期"])
    bad_out = _semantic_bad_indexes(out_rows, cols["日期"])

    residual = 0
    for kind, patterns in PATTERNS.items():
        for name, pattern in patterns.items():
            if kind == "日期" and not name.startswith("语义非法"):
                exclude_src, exclude_out = bad_src, bad_out
            else:
                exclude_src, exclude_out = set(), set()
            before = count_rows(src_rows, cols[kind], pattern, exclude_src)
            after = count_rows(out_rows, cols[kind], pattern, exclude_out)
            if name.startswith("语义非法"):
                # 不可清洗项(日期不存在):只报告,要求出现在报告"未处理项"里,不计入不合格
                mark = "待核对" if after else "OK"
            elif name.startswith("非数值残留") or name.startswith("非标准格式"):
                mark = "OK" if after == 0 else "残留"
                residual += 1 if after else 0
            else:
                mark = ("已清洗" if after == 0 else "残留") if before else "-"
                residual += 1 if after else 0
            print(f"{kind:<5}{name:<30}{before:>7}{after:>7}   {mark}")
    print("-" * 72)
    if residual:
        print(f"结论:**不合格** —— 有 {residual} 项脏点在洗后仍存在(要么修规则,要么在报告里如实列为未处理)")
        return 1
    print("结论:通过 —— 三类脏点(金额/日期/数量)洗后均为 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# ---------------------------------------------------------------------------
# 升级说明(相对交付版 核查脚本_洗后脏点对账.py / md5 090328331f14688bb1622eaea6bd0322)
# 1) 日期段改为语义解析分三类:可转的格式非标准(修完应为 0) / 语义非法(转不了,待核对) /
#    单位类(由「数量」组的粘连与非数值残留承担,脚本不复制产品侧单位词表)。
# 2) _semantic_bad_date 由「只认 YYYY-MM-DD 形态」升级为**任一日期形态**(含 2024.02.30、
#    20240830 之类);否则点分/斜杠分隔的非法值会同时落进「点/斜杠分隔」与「非标准格式」两个
#    "应清零"分项 —— 那两项在正确修复(保留非法原值 + 登记未处理)后必然非 0,脚本永远红。
# 3) 语义非法行从其余日期分项计数中排除(同一行只进一个桶)。
# 4) 用法错(参数个数不对 / 文件不存在)统一返回 2,不再抛 traceback。
# ---------------------------------------------------------------------------
