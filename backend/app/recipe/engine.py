"""配方引擎：recipe.json 序列化 / 校验 / 依赖分析 / 重放。

依据 7.3 recipe.json 结构；未知操作不崩（标记 unknown 并拒绝执行），
执行前必须通过字段级校验（含依赖列存在性）。
"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from ..operations.base import OpContext, OperationRegistry

RECIPE_SCHEMA_ID = "clean-recipe/v1"
MAX_OPS = 100


class RecipeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def new_recipe(name: str, source: Dict[str, Any], operations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """构造 recipe.json 主结构（签名在导出时统一写入）。"""
    return {
        "schema_id": RECIPE_SCHEMA_ID,
        "name": name,
        "source": source,
        "operations": operations,
    }


def validate_recipe(recipe: Dict[str, Any], columns: Optional[List[str]] = None) -> List[str]:
    """字段级校验。返回错误列表（空 = 通过）。不校验签名。"""
    errors: List[str] = []
    if recipe.get("schema_id") != RECIPE_SCHEMA_ID:
        errors.append(f"schema_id 应为 {RECIPE_SCHEMA_ID}")
    ops = recipe.get("operations")
    if not isinstance(ops, list) or not ops:
        errors.append("operations 不能为空")
        return errors
    if len(ops) > MAX_OPS:
        errors.append(f"operations 超过上限 {MAX_OPS}")
    for idx, op in enumerate(ops):
        op_name = op.get("op") if isinstance(op, dict) else None
        if not op_name:
            errors.append(f"第 {idx + 1} 步缺少 op")
            continue
        cls = OperationRegistry.get(op_name)
        if cls is None:
            errors.append(f"第 {idx + 1} 步操作 {op_name} 未知")
            continue
        if columns is not None:
            ctx = OpContext(columns=columns, rows=[], params=op.get("params", {}))
            op_label = (cls.description or op_name).split("：")[0]
            errors.extend(f"第 {idx + 1} 步 {op_label}：{e}" for e in cls().validate(ctx))
    return errors


def describe_recipe(recipe: Dict[str, Any]) -> List[str]:
    """人类可读配方描述（预览用）。"""
    lines = []
    ops = recipe.get("operations", [])
    for idx, op in enumerate(ops, 1):
        cls = OperationRegistry.get(op.get("op", ""))
        if cls is None:
            lines.append(f"{idx}. 未知操作 {op.get('op')}")
        else:
            try:
                lines.append(f"{idx}. {cls().describe(op.get('params', {}))}")
            except Exception:
                lines.append(f"{idx}. {op.get('op')}")
    return lines


def recipe_signature(recipe: Dict[str, Any]) -> str:
    """内容签名（防篡改，供 execute 前校验）。

    签名对象为除 `_signature` 自身外的全部字段（排序序列化，内容等价 = 签名一致），
    因此「先签名再写入」与「读取已签名配方再复算」结果相同。
    """
    body = {k: v for k, v in recipe.items() if k != "_signature"}
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sign_recipe(recipe: Dict[str, Any]) -> Dict[str, Any]:
    """就地写入 `_signature` 并返回同一 dict（生成侧使用）。"""
    recipe["_signature"] = recipe_signature(recipe)
    return recipe


def verify_recipe_signature(recipe: Dict[str, Any]) -> Dict[str, Any]:
    """校验配方签名（执行侧使用，防篡改）。

    返回五要素：verified（是否通过）/ reason（OK / MISSING_SIGNATURE / SIGNATURE_MISMATCH）
    / expected（配方内声明）/ actual（按内容复算）。
    无签名（内部新建、尚未导出的配方）不视为篡改，由调用方决定是否放行。
    """
    expected = recipe.get("_signature")
    actual = recipe_signature(recipe)
    if not expected:
        return {"verified": False, "reason": "MISSING_SIGNATURE", "expected": None, "actual": actual, "signature": actual}
    if expected != actual:
        return {"verified": False, "reason": "SIGNATURE_MISMATCH", "expected": expected, "actual": actual, "signature": actual}
    return {"verified": True, "reason": "OK", "expected": expected, "actual": actual, "signature": actual}


_INPUT_COLUMN_KEYS = ("column", "columns", "subset")
_OUTPUT_COLUMN_KEYS = ("new_columns", "new_column", "new_name")
_IDENT_RE = re.compile(r"[A-Za-z_\u4e00-\u9fa5][A-Za-z0-9_\u4e00-\u9fa5]*")
# 列演化规则：操作执行后列集合的变化（用于依赖可达性判断）
_DROP_KEYS = {
    "column_delete": ("columns", "column"),
    "column_rename": ("column",),
    "column_merge": ("columns",),
    "column_split": ("column",),
}
_ADD_KEYS = {"column_rename": ("new_name",), "column_merge": ("new_name",), "column_derive": ("new_column",), "column_split": ("new_columns",)}


def analyze_dependencies(recipe: Dict[str, Any], columns: Optional[List[str]] = None) -> Dict[str, Any]:
    """配方依赖分析：输入列（dependencies）/ 新增列（new_columns）/ 内部列 + 满足性。

    - 按参数语义静态解析（不执行数据）：column / columns / subset = 依赖列；
      new_name / new_column / new_columns = 新增列。
    - 逐步骤模拟列集合演化（新增 / 删除 / 改名），判断依赖列是否在前序步骤后仍可达；
      columns 为 None 时不做存在性判定（仅解析依赖结构）。
    - 未知操作如实标注（标记不崩），并入 missing / satisfied 判定。
    """
    ops = recipe.get("operations", []) or []
    known = [c for c in (columns or []) if isinstance(c, str)]
    available: List[str] = list(known)
    dependencies: List[str] = []
    new_columns: List[str] = []
    internal_columns: List[str] = []
    unknown_operations: List[str] = []
    missing_columns: List[str] = []

    def _collect(value: Any) -> List[str]:
        if isinstance(value, str):
            return [value] if value else []
        if isinstance(value, (list, tuple)):
            return [v for v in value if isinstance(v, str) and v]
        return []

    for spec in ops:
        name = spec.get("op", "")
        cls = OperationRegistry.get(name)
        params = spec.get("params", {}) or {}
        if cls is None:
            if name and name not in unknown_operations:
                unknown_operations.append(name)
            continue

        step_inputs: List[str] = []
        for key in _INPUT_COLUMN_KEYS:
            for col in _collect(params.get(key)):
                if col not in dependencies:
                    dependencies.append(col)
                if col not in step_inputs:
                    step_inputs.append(col)
        for key in _OUTPUT_COLUMN_KEYS:
            for col in _collect(params.get(key)):
                if col not in new_columns:
                    new_columns.append(col)
        for col in _collect(params.get("internal_columns")):
            if col not in internal_columns:
                internal_columns.append(col)
        if name == "column_derive":
            # 表达式引用的列无法从参数键直接读出：仅当与已知列名精确匹配时计入依赖
            for token in _IDENT_RE.findall(str(params.get("expression", ""))):
                if token in available and token not in dependencies:
                    dependencies.append(token)
                    step_inputs.append(token)

        if columns is not None:
            for col in step_inputs:
                if col not in available and col not in missing_columns:
                    missing_columns.append(col)

        # 列集合演化（供后续步骤判断可达性）
        for key in _DROP_KEYS.get(name, ()):  # type: ignore[arg-type]
            for col in _collect(params.get(key)):
                if col in available:
                    available.remove(col)
        for key in _ADD_KEYS.get(name, ()):  # type: ignore[arg-type]
            for col in _collect(params.get(key)):
                if col not in available:
                    available.append(col)

    return {
        "dependencies": dependencies,
        "new_columns": new_columns,
        "internal_columns": internal_columns,
        "missing_columns": missing_columns,
        "unknown_operations": unknown_operations,
        "satisfied": not missing_columns and not unknown_operations,
    }


def replay(recipe: Dict[str, Any], columns: List[str], rows: List[List[Any]]) -> Dict[str, Any]:
    """重放配方（dry-run / 正式执行共用）。返回最终行列 + 转换日志。

    - 逐步骤执行；任一步失败立即停止并携带失败日志（不产生半成品结果）。
    - 未知操作 / 校验失败在调用前应已拦截，这里仍做防御。
    """
    errors = validate_recipe(recipe, columns)
    if errors:
        raise RecipeError("RECIPE_INVALID", "；".join(errors[:10]))

    cur_columns = list(columns)
    cur_rows = [list(r) for r in rows]
    transform_log: List[Dict[str, Any]] = []
    for idx, op_spec in enumerate(recipe["operations"]):
        op_name = op_spec["op"]
        cls = OperationRegistry.get(op_name)
        if cls is None:
            raise RecipeError("UNKNOWN_OP", f"第 {idx + 1} 步操作 {op_name} 未知")
        op = cls()
        ctx = OpContext(columns=cur_columns, rows=cur_rows, params=op_spec.get("params", {}))
        try:
            result = op.apply(ctx)
        except Exception as exc:
            raise RecipeError("OP_FAILED", f"第 {idx + 1} 步 {op_name} 失败: {exc}") from exc
        if not result.ok:
            raise RecipeError("OP_FAILED", f"第 {idx + 1} 步 {op_name} 未通过")
        entry = {"step": idx + 1, "op": op_name}
        entry.update(result.log)
        # 执行过程每步写明"作用对象"（列名，或「全表」），报告/前端据此显示"改了什么"
        entry.setdefault("target", _target_of(op_spec.get("params", {})))
        transform_log.append(entry)
        cur_columns = result.columns
        cur_rows = result.rows

    return {"columns": cur_columns, "rows": cur_rows, "transform_log": transform_log}


def _target_of(params: Dict[str, Any]) -> str:
    """把步骤参数折算成"作用对象"文案 —— 列名（可多列，顿号分隔），无列参数＝「全表」。"""
    names: List[str] = []
    for key in ("column", "columns", "subset", "sources", "base_column"):
        value = (params or {}).get(key)
        if isinstance(value, str) and value:
            names.append(value)
        elif isinstance(value, (list, tuple)):
            names.extend(str(v) for v in value if v)
    seen: List[str] = []
    for name in names:
        if name not in seen:
            seen.append(name)
    return "、".join(seen) if seen else "全表"


def export_recipe_json(recipe: Dict[str, Any], out_path: str) -> str:
    """导出 recipe.json 到磁盘（含 signature，供留档 / 复用）。"""
    recipe = sign_recipe(dict(recipe))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(recipe, f, ensure_ascii=False, indent=2)
    return out_path
