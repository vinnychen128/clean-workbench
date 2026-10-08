# SPDX-License-Identifier: Apache-2.0
"""提示词模板 —— 提示词版本化，内容里不含任何数据值。

提示词只描述：① 任务与输出 JSON schema；② 受控语义类型枚举；③ 可用算子目录。
模型永远看不到原始单元格值，只能看到形态标签与列级统计（红线）。
"""
from __future__ import annotations

from typing import Any, Dict, List

from .config import SEMANTIC_TYPES

# 提示词版本号：任何措辞改动都必须让本号 +1（缓存与台账按版本区分）
PROMPT_VERSION = "ai-p1"

# ── 可用算子目录（算子名的唯一权威仍是 operations/base.py 登记表）──
#  这里只给模型「选谁 + 怎么填参数」的说明，最终合法性由 OperationRegistry 复核。
OP_CATALOG: List[Dict[str, str]] = [
    {"op": "cell_trim", "params": "column 或 columns", "for": "首尾/内部多余空白"},
    {"op": "cell_fullwidth", "params": "column 或 columns", "for": "全角字符/全角数字"},
    {"op": "cell_amount_clean", "params": "column", "for": "金额：货币符号、千分位、括号负数"},
    {"op": "cell_date_normalize", "params": "column", "for": "日期多格式统一为 YYYY-MM-DD"},
    {"op": "cell_unit_convert", "params": "column, from, to", "for": "单位换算；to 填「纯数值」= 剥离计数单位"},
    {"op": "cell_text_replace", "params": "column 或 columns, old, new, regex", "for": "文本/单位粘连替换"},
    {"op": "cell_case", "params": "column 或 columns, mode(upper|lower|title)", "for": "大小写统一"},
    {"op": "cell_fill_missing", "params": "column, method(constant|ffill|bfill|mean), value", "for": "缺失值填充"},
    {"op": "row_dedupe", "params": "subset(可选，列名数组)", "for": "完全重复行"},
    {"op": "row_delete", "params": "where(列名→值)", "for": "按条件删行"},
    {"op": "column_rename", "params": "column, new_name", "for": "列改名"},
    {"op": "column_split", "params": "column, separator 或 regex, new_columns", "for": "拆列"},
    {"op": "column_merge", "params": "columns, separator, new_name", "for": "合列"},
]

_JSON_CONTRACT = """{
  "advice": [
    {
      "column": "<必须来自给定列名>",
      "semantic_type": "<受控枚举之一>",
      "evidence": ["<形态标签 占比%>", "..."],
      "suggested_ops": [{"op": "<算子名>", "params": {...}}],
      "rationale": "<一句话中文理由>",
      "confidence": 0.0
    }
  ]
}"""


def build_column_advice_messages(
    profiles: List[Dict[str, Any]],
    columns: List[str],
    semantic_types: List[str] | None = None,
) -> List[Dict[str, str]]:
    """构造「列语义建议」请求消息（只带形态画像，不带任何数据值）。"""
    types = semantic_types or SEMANTIC_TYPES
    profile_lines = []
    for p in profiles:
        dist = "，".join(
            f'{d["profile"]} {round(d["ratio"] * 100)}%' for d in p.get("profile_distribution", [])[:5]
        )
        profile_lines.append(
            f'- 列「{p["column"]}」：非空率 {round(p["non_empty_rate"] * 100)}%，'
            f'唯一值 {p["unique_count"]}，长度 {p["length_min"]}~{p["length_max"]}，形态分布：{dist or "（空列）"}'
        )
    op_lines = [f'- {o["op"]}（参数：{o["params"]}）—— 适用：{o["for"]}' for o in OP_CATALOG]

    system = (
        "你是本地数据清洗台的表结构理解助手。你只做「看懂列语义 + 给出清洗建议」，"
        "永远不会修改任何数据值。你只能输出 JSON，不能输出任何解释性文字或代码块。"
    )
    user = (
        "下面是若干列的形态画像（已脱敏：只有统计量与形态标签，没有任何原始数据值）。\n"
        "请为每一列判断语义类型并给出清洗建议。\n\n"
        "【受控语义类型】只能从中选一个，禁止自造：" + "、".join(types) + "\n\n"
        "【可用算子目录】只能从中选 op，禁止自造算子名：\n" + "\n".join(op_lines) + "\n\n"
        "【列画像】\n" + "\n".join(profile_lines) + "\n\n"
        "【输出要求】严格输出如下 JSON 结构，confidence 为 0~1 的小数，evidence 用形态标签与占比：\n"
        + _JSON_CONTRACT
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_report_explain_messages(summary: Dict[str, Any]) -> List[Dict[str, str]]:
    """构造「体检报告人话版」请求消息（只带确定性统计事实，不带数据值）。"""
    lines = [
        f'数据规模：{summary.get("row_count")} 行 × {summary.get("column_count")} 列',
        f'体检结论：{summary.get("profile_conclusion", "")}',
        f'质量结论：{summary.get("quality_conclusion", "")}',
        f'未处理项数量：{summary.get("unhandled_count")}',
    ]
    issues = summary.get("issues", [])
    if issues:
        lines.append("检出的问题清单：")
        for it in issues[:20]:
            lines.append(
                f'- [{it.get("severity")}] {it.get("label") or it.get("name") or it.get("id")}'
                f'（命中 {it.get("count")} 处，列：{it.get("column", "全表")}）'
            )
    if summary.get("unmet"):
        lines.append("未达标指标：" + "；".join(str(u) for u in summary["unmet"][:10]))
    if summary.get("overrides_ack"):
        lines.append("存在经用户确认放行的越权项。")

    system = (
        "你是本地数据清洗台的报告讲解助手。你只把已有的统计结论翻译成结构化中文说明，"
        "绝不新增、推测或修改任何数值。只输出 JSON，不要输出多余文字。"
    )
    user = (
        "下面是一次清洗的确定性统计事实（数字均由程序算出，不要改动也不要补充新数字）。\n"
        "请输出：① 一句话总述；② 3~5 条要点；③ 面向用户的三条下一步建议（按优先级）。\n\n"
        "【统计事实】\n" + "\n".join(lines) + "\n\n"
        "【输出 JSON 结构】\n"
        '{"summary": "<一句话>", "bullets": ["<要点>"], "next_actions": ["<建议>"]}'
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
