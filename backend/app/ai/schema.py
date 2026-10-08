# SPDX-License-Identifier: Apache-2.0
"""输入 / 输出 schema 与受控枚举校验 —— 模型输出越界一律视为不合规。"""
from __future__ import annotations

import json
from typing import Any

from .config import SEMANTIC_TYPES

# 说明：受控枚举的唯一来源在 config；本模块只做「越界即不合规」的校验。


class SchemaError(Exception):
    """输出不合规。"""


def _check_enum(value: Any, allowed: list[str], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise SchemaError(f"{field} 不在受控枚举内: {value!r}")
    return value


_COLUMN_ADVICE_SCHEMA = {
    "type": "object",
    "required": ["advice"],
    "properties": {
        "advice": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["column", "semantic_type", "evidence", "suggested_ops", "rationale", "confidence"],
                "properties": {
                    "column": {"type": "string"},
                    "semantic_type": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "suggested_ops": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["op", "params"],
                            "properties": {
                                "op": {"type": "string"},
                                "params": {"type": "object"},
                            },
                        },
                    },
                    "rationale": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        }
    },
}


def validate_column_advice(data: Any, columns: list[str]) -> dict:
    """
    校验列语义建议输出。

    - advice 必为数组
    - semantic_type ∈ SEMANTIC_TYPES
    - suggested_ops 的 op 必须为字符串（算子名合法性由 service 层再用算子目录校验）
    - confidence ∈ [0, 1]
    """
    if not isinstance(data, dict):
        raise SchemaError("输出不是 JSON 对象")
    advice = data.get("advice")
    if not isinstance(advice, list):
        raise SchemaError("advice 字段必须是数组")

    col_set = set(columns)
    normalized = []
    for item in advice:
        if not isinstance(item, dict):
            raise SchemaError("advice 元素必须是对象")
        col = item.get("column")
        if not isinstance(col, str):
            raise SchemaError("column 必须是字符串")
        if col not in col_set:
            raise SchemaError(f"未在请求中的列: {col}")
        semantic_type = _check_enum(item.get("semantic_type"), SEMANTIC_TYPES, "semantic_type")

        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not all(isinstance(e, str) for e in evidence):
            raise SchemaError("evidence 必须是字符串数组")

        suggested_ops = item.get("suggested_ops", [])
        if not isinstance(suggested_ops, list):
            raise SchemaError("suggested_ops 必须是数组")
        ops_clean = []
        for op in suggested_ops:
            if not isinstance(op, dict):
                raise SchemaError("suggested_ops 元素必须是对象")
            op_name = op.get("op")
            if not isinstance(op_name, str) or not op_name:
                raise SchemaError("op 必须是非空字符串")
            params = op.get("params", {})
            if not isinstance(params, dict):
                raise SchemaError("params 必须是对象")
            ops_clean.append({"op": op_name, "params": params})

        rationale = item.get("rationale", "")
        if not isinstance(rationale, str):
            raise SchemaError("rationale 必须是字符串")

        confidence = item.get("confidence", 0.0)
        if not isinstance(confidence, (int, float)) or not (0.0 <= float(confidence) <= 1.0):
            raise SchemaError("confidence 必须在 [0, 1] 内")

        normalized.append({
            "column": col,
            "semantic_type": semantic_type,
            "evidence": evidence,
            "suggested_ops": ops_clean,
            "rationale": rationale,
            "confidence": float(confidence),
        })

    return {"advice": normalized}


def parse_json_output(raw_text: str) -> Any:
    """从模型文本中提取 JSON（容忍 ```json 包裹与前后噪声）。"""
    if not isinstance(raw_text, str):
        raise SchemaError("模型输出不是文本")
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()
    # 截取首个 { 到末个 }
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise SchemaError("未找到 JSON 对象")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise SchemaError(f"JSON 解析失败: {exc}") from exc


def validate_report_explain(data: Any) -> dict:
    """
    校验「体检报告人话版」输出：一句话总述 + 要点数组 + 下一步建议数组。

    只做结构校验，不校验数值（数值一律以本地表格为准，模型不得改动）。
    """
    if not isinstance(data, dict):
        raise SchemaError("输出不是 JSON 对象")

    summary = data.get("summary")
    if not isinstance(summary, str) or summary.strip() == "":
        raise SchemaError("summary 必须是非空字符串")

    bullets = data.get("bullets", [])
    if not isinstance(bullets, list) or not all(isinstance(b, str) for b in bullets):
        raise SchemaError("bullets 必须是字符串数组")

    next_actions = data.get("next_actions", [])
    if not isinstance(next_actions, list) or not all(isinstance(a, str) for a in next_actions):
        raise SchemaError("next_actions 必须是字符串数组")

    return {
        "summary": summary.strip(),
        "bullets": [b.strip() for b in bullets if b.strip()],
        "next_actions": [a.strip() for a in next_actions if a.strip()],
    }


# 体检报告人话版的固定免责注（disclaimer 字段必须非空）
REPORT_DISCLAIMER = "AI 生成，数值以上方表格为准"
