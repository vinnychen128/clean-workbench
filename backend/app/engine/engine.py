"""执行引擎：清洗状态机 + 人工确认门 + 回退。

关键约定：
- 人工确认门：confirmed=False 时 execute 拒绝执行（AWAITING_HITL）。
- 前后校验回退 ≤2 次；超限不自动覆盖，须人工介入。
- 原件只读：执行时复制数据引用为清洗副本（data_ref 指向清洗副本），绝不原地改写。
"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..recipe.engine import RecipeError, analyze_dependencies, replay, validate_recipe, verify_recipe_signature
from ..state import CleanState

MAX_RETRY = 2


class EngineError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def build_plan(state: CleanState, recipe: Dict[str, Any], columns: Optional[List[str]] = None) -> Dict[str, Any]:
    """生成配方：校验 + 依赖分析 + 描述 + 风险标注。不执行。

    columns：解析后的列名列表；传入时执行列存在性校验（缺列执行前提示）。
    返回 dependencies / new_columns / internal_columns / dependency_analysis（依赖分析结果）。
    """
    errors = validate_recipe(recipe, columns=columns)
    if errors:
        raise EngineError("PLAN_INVALID", "；".join(errors[:10]))
    analysis = analyze_dependencies(recipe, columns=columns)
    if analysis["missing_columns"] or analysis["unknown_operations"]:
        raise EngineError(
            "PLAN_INVALID",
            "；".join(
                [f"缺少列: {c}" for c in analysis["missing_columns"] if c]
                + [f"未知操作: {o}" for o in analysis["unknown_operations"]]
            ),
        )
    state.rules_plan = recipe
    state.recipe_id = recipe.get("recipe_id", f"recipe-{len(state.thread_id)}")
    state.stage = "plan"
    # 缺陷修复②（执行口径一致）：新配方一旦生成，上一轮的执行记录 / 前后校验 / 报告即失效，
    # 否则确认门（新配方 N 步）与执行屏、报告、导出（旧配方 1 步）会四方口径不一致。
    state.transform_log = []
    state.verify = {}
    state.report = {}
    return {
        "recipe_id": state.recipe_id,
        "steps": recipe.get("operations", []),
        "description": _describe_ops(recipe),
        "risk_flags": _risk_flags(recipe),
        "dependencies": analysis["dependencies"],
        "new_columns": analysis["new_columns"],
        "internal_columns": analysis["internal_columns"],
        "dependency_analysis": {
            "satisfied": analysis["satisfied"],
            "missing_columns": analysis["missing_columns"],
            "unknown_operations": analysis["unknown_operations"],
        },
    }


def _describe_ops(recipe: Dict[str, Any]) -> List[str]:
    from ..recipe.engine import describe_recipe
    return describe_recipe(recipe)


def _risk_flags(recipe: Dict[str, Any]) -> List[str]:
    """风险标注：删除类操作 / 均值填充等需人工留意。"""
    flags = []
    for op in recipe.get("operations", []):
        name = op.get("op", "")
        if name in ("row_delete", "row_keep", "column_delete"):
            flags.append(f"含删除类操作 {name}（人工门必须确认）")
        if name == "cell_fill_missing" and op.get("params", {}).get("method") == "mean":
            flags.append("含均值填充（可能掩盖真实分布，建议复核）")
    return flags


def confirm_plan(state: CleanState, approve: bool, reason: Optional[str] = None) -> Dict[str, Any]:
    """人工确认门：approve=True 放行；False 拒绝并终止本线。"""
    if state.stage not in ("plan", "awaiting_confirm"):
        raise EngineError("STATE_MISMATCH", f"当前阶段 {state.stage} 不接受确认")
    state.confirmed = bool(approve)
    state.confirm_reason = reason
    state.stage = "confirmed" if approve else "rejected"
    return {"confirmed": state.confirmed, "reason": reason, "stage": state.stage}


def execute_recipe(state: CleanState, columns: List[str], rows: List[List[Any]]) -> Dict[str, Any]:
    """执行配方：未确认拒绝；签名校验；执行产生清洗副本引用；任一步失败不留半成品。"""
    if not state.confirmed:
        state.stage = "awaiting_confirm"
        raise EngineError("NOT_CONFIRMED", "配方未经人工确认，拒绝执行")
    recipe = state.rules_plan
    if not recipe:
        raise EngineError("NO_PLAN", "无配方可执行")
    # 数据完整性：带签名配方必须签名一致；不一致即篡改，拒绝执行并报错（fail-loud）
    signature = verify_recipe_signature(recipe)
    if signature["reason"] == "SIGNATURE_MISMATCH":
        state.add_error("execute", "配方签名不匹配，疑似被篡改，拒绝执行")
        state.signature_check = signature
        state.stage = "failed"
        raise EngineError("RECIPE_SIGNATURE_MISMATCH", "配方签名不匹配（疑似篡改），拒绝执行")
    state.signature_check = signature
    try:
        result = replay(recipe, columns, rows)
    except RecipeError as exc:
        state.add_error("execute", exc.message)
        state.stage = "failed"
        raise EngineError(exc.code, exc.message) from exc

    state.data_ref = f"clean://{state.thread_id}"  # 指向清洗副本
    state.transform_log = result["transform_log"]
    state.stage = "executed"
    # 缺陷修复②（执行口径一致）：本次执行结果使上一轮的前后校验与报告失效，
    # 须按新结果重算校验、重建报告，避免报告屏「三、质量对比」沿用旧指标。
    state.verify = {}
    state.report = {}
    return {
        "columns": result["columns"],
        "rows": result["rows"],
        "transform_log": result["transform_log"],
        "data_ref": state.data_ref,
    }


def begin_verify_round(state: CleanState, passed: bool, metrics: Dict[str, Any],
                       unmet: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """前后校验：passed=False 时 retry_count+1；>MAX_RETRY 转 AWAITING_HITL。

    `unmet`（对象数组）随本轮结果落状态，供报告/首屏按同一份明细渲染。
    """
    state.verify = {"passed": passed, "metrics": metrics, "unmet": list(unmet or []),
                    "round": state.retry_count + 1}
    if not passed:
        state.retry_count += 1
        if state.retry_count > MAX_RETRY:
            state.stage = "awaiting_hitl"
            state.add_error("verify", f"前后校验连续失败 {MAX_RETRY} 次，转人工介入")
            return {"passed": False, "awaiting_hitl": True, "round": state.retry_count}
        state.stage = "verify_failed"
        return {"passed": False, "retryable": True, "round": state.retry_count}
    state.stage = "verified"
    return {"passed": True, "round": state.retry_count + 1}


def check_coverage(state: CleanState, before: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """覆盖校验：体检命中的**高危**问题必须有配方操作覆盖，否则不放行。

    判据与前端 `riskGate` 同一份（`reporter.HANDLED_BY_OPS`，单一来源）：
    - 只看 `severity == "high"` 且**体检命中**的项（未命中不判）；
    - 命中项在配方操作集合里找不到任何可用操作 → 列入 `uncovered`，`covered=False`；
    - 放行条件：`uncovered` 为空，或调用方带越权确认（`override.ack=True` + 说明）。
    - `before` 传入且状态里还没有体检结果时**就地补算体检** —— 跳过 /api/eda 不能成为绕过硬门的路径。
    """
    from ..report.reporter import HANDLED_BY_OPS, ISSUE_LABELS

    profile = state.profile or {}
    if not profile.get("issues") and before:
        from ..detectors.base import DetectorRegistry
        profile = DetectorRegistry.run_all(list(before.get("columns") or []),
                                           [list(r) for r in (before.get("rows") or [])], verbosity=1)
        state.profile = profile
    ops = {op.get("op") for op in (state.rules_plan or {}).get("operations", []) if isinstance(op, dict)}
    high_issues: List[Dict[str, Any]] = []
    uncovered: List[Dict[str, Any]] = []
    for issue in profile.get("issues") or []:
        if not isinstance(issue, dict) or issue.get("severity") != "high":
            continue
        rows = issue.get("rows") or []
        rows_total = issue.get("rows_total")
        rows_total = len(rows) if rows_total is None else int(rows_total)
        if not rows_total:
            continue  # 体检未命中：不纳入判定（同理）
        name = issue.get("issue_name", "")
        handlers = list(HANDLED_BY_OPS.get(name, ()))
        high_issues.append({"issue_name": name, "affected_rows": rows_total, "handlers": handlers})
        if set(handlers) & ops:
            continue
        uncovered.append({
            "issue_name": name,
            "label": ISSUE_LABELS.get(name, name),
            "severity": "high",
            "affected_rows": rows_total,
            "handlers": handlers,
            "message": f"高危问题「{ISSUE_LABELS.get(name, name)}」未被配方覆盖（{rows_total} 行）："
                       f"可用操作 {'/'.join(handlers) if handlers else '无'}",
        })
    return {"ok": not uncovered, "uncovered_high": uncovered,
            "covered": not uncovered, "uncovered": uncovered,
            "high_count": len(high_issues), "uncovered_high_count": len(uncovered)}


def record_override(state: CleanState, coverage: Dict[str, Any], note: str,
                    skipped: Optional[List[str]] = None) -> Dict[str, Any]:
    """记录越权放行（留痕）：跳过项 + 说明 + 时间，落状态；
    报告 `3_quality.overrides[]` 与「未处理项」标注据此生成（仍是"未处理"，不改成"已处理"）。"""
    from datetime import datetime

    uncovered = list(coverage.get("uncovered") or [])
    names = [str(n) for n in (skipped or [])] or [str(u.get("issue_name")) for u in uncovered if u.get("issue_name")]
    entry = {
        "ack": True,
        "skipped": names,
        "note": note,
        "at": datetime.now().isoformat(timespec="seconds"),
        "uncovered": uncovered,
    }
    state.overrides = entry
    return entry
