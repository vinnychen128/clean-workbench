"""LangGraph 编排图：8 节点 + 人工确认门中断 + 检查点。

节点：parse → eda → plan → confirm（HITL interrupt）→ execute
      → verify_check → report_build → export。

命名硬约束：LangGraph 禁止节点名与状态键同名，否则 build_pipeline()
抛 `ValueError: '<name>' is already being used as a state key`。状态键 verify / report
取自运行状态表的既有字段名，故节点名避让为 verify_check / report_build
（映射见 NODE_STATE_KEY ）。

- 中断点：confirm 节点内动态 interrupt()（人工门），须注入 checkpointer
  （服务端 SqliteSaver / 测试 MemorySaver）；恢复经 Command(resume=...) 注入决策。
- 校验失败 ≤2 次回退（engine.begin_verify_round 控制），超限转 AWAITING_HITL 并收尾留痕。
- 状态对象 CleanState 为大对象引用，数据本体走 data_ref（不进图状态）。
"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, Optional, Tuple

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ..engine.engine import EngineError, begin_verify_round, build_plan, execute_recipe
from ..state import CleanState

# 业务节点顺序（与前端节点表、/api/run/{run_id} 节点进度一致）
NODE_ORDER: Tuple[str, ...] = ("parse", "eda", "plan", "confirm", "execute",
                               "verify_check", "report_build", "export")

# 节点名 → 其写入的状态键（两者不得同名，见模块 docstring）
NODE_STATE_KEY: Dict[str, str] = {"verify_check": "verify", "report_build": "report"}


def _now() -> str:
    now = datetime.now()
    return (f"{now.year}-{now.month:02d}-{now.day:02d} "
            f"{now.hour:02d}:{now.minute:02d}:{now.second:02d}")


def _is_interrupt(exc: BaseException) -> bool:
    return "Interrupt" in type(exc).__name__


def _decision(payload: Any) -> Tuple[bool, str]:
    """解析人工门恢复载荷：True / False / {"approve": bool, "reason": str}。"""
    if isinstance(payload, dict):
        approved = payload.get("approve", payload.get("confirmed", False))
        return bool(approved), str(payload.get("reason", "") or "")
    return bool(payload), ""


class GraphIO:
    """供编排图调用的 IO 适配器（由服务层注入，测试可替换）。

    - load_before：清洗前原件引用（只读，原件不可变）
    - load_after：清洗副本；未执行时回退为原件，保证 compare 有输入
    - save：写清洗副本
    - store / record_fn：节点执行埋点（执行记录，落 node_runs 表）
    """

    def __init__(self, load_fn: Optional[Callable[[], Any]] = None,
                 save_fn: Optional[Callable[[Any], None]] = None,
                 store: Optional[Any] = None,
                 load_after_fn: Optional[Callable[[], Any]] = None,
                 record_fn: Optional[Callable[..., None]] = None):
        self._load = load_fn
        self._load_after = load_after_fn or load_fn
        self._save = save_fn
        self.store = store
        self._record = record_fn

    def load_before(self) -> Any:
        return self._load() if self._load else None

    def load_after(self) -> Any:
        return self._load_after() if self._load_after else None

    def load(self, after: bool = False) -> Any:
        return self.load_after() if after else self.load_before()

    def save(self, data: Any) -> None:
        if self._save:
            self._save(data)

    def record(self, node_name: str, status: str, started_at: str,
               ended_at: str, error: Optional[str] = None) -> None:
        """节点执行落表。无记录器时跳过（纯图单元测试场景）。"""
        if self._record is None:
            return
        self._record(node_name, status, started_at, ended_at, error)


def build_pipeline(io: GraphIO, checkpointer: Optional[Any] = None) -> Any:
    """构建并编译 LangGraph 状态图。

    checkpointer：检查点持久化器（服务端 SqliteSaver / 测试 MemorySaver）。
    注入后 confirm 节点的 interrupt() 可挂起运行，并由 Command(resume=...) 跨会话恢复
    未注入时 confirm 仅就地标注 AWAITING_HITL 并结束本次运行。

    编译不使用 interrupt_before（节点名与状态键撞名已修），中断完全由 confirm 节点内
    的动态 interrupt() 承担。
    """

    def _wrap(name: str, fn: Callable[[CleanState], Dict[str, Any]]):
        """节点包装：执行记录 + 中断/异常如实落表（fail-loud）。"""

        def runner(state: CleanState) -> Dict[str, Any]:
            started = _now()
            try:
                out = fn(state)
            except BaseException as exc:
                interrupting = _is_interrupt(exc)
                detail = f"{type(exc).__name__}: {exc}"[:300]
                io.record(name, "AWAITING_HITL" if interrupting else "FAILED",
                          started, _now(), None if interrupting else detail)
                raise
            io.record(name, "COMPLETED", started, _now())
            return out

        runner.__name__ = name
        return runner

    def parse_node(state: CleanState) -> Dict[str, Any]:
        state.stage = "parsing"
        # 数据已在 /api/parse 完成解析；此处仅校验引用并推进
        if not state.data_ref:
            state.add_error("parse", "缺少数据引用")
        return {"stage": "parsed", "errors": state.errors}

    def eda_node(state: CleanState) -> Dict[str, Any]:
        from ..detectors.base import DetectorRegistry
        data = io.load_before() or {}
        profile = DetectorRegistry.run_all(data.get("columns", []), data.get("rows", []), verbosity=1)
        state.profile = profile
        return {"profile": profile, "stage": "eda"}

    def plan_node(state: CleanState) -> Dict[str, Any]:
        from ..recipe.engine import new_recipe
        cur = state.rules_plan or {}
        if cur.get("schema_id") and cur.get("operations"):
            recipe = cur  # 已由 /api/plan 或 /api/recipe-import 生成（含签名），沿用不覆盖
        else:
            recipe = new_recipe("auto-plan",
                                {"thread_id": state.thread_id, "source": state.source},
                                cur.get("operations", []))
        data = io.load_before() or {}
        try:
            build_plan(state, recipe, columns=data.get("columns", []))
        except EngineError as exc:
            state.add_error("plan", exc.message)
            return {"stage": state.stage, "errors": state.errors}
        state.stage = "awaiting_confirm"  # 人工门：等待 confirm 决策
        return {"rules_plan": state.rules_plan, "recipe_id": state.recipe_id,
                "stage": state.stage, "errors": state.errors}

    def confirm_node(state: CleanState) -> Dict[str, Any]:
        plan = state.rules_plan or {}
        payload = {
            "kind": "hitl_confirm",
            "thread_id": state.thread_id,
            "question": "配方待人工确认后执行（人工门）",
            "steps": len(plan.get("operations", [])),
        }
        if checkpointer is None:
            # 无检查点：不具备跨会话挂起/恢复能力，仅就地标注等待人工（不误判为已拒绝）
            state.stage = "awaiting_confirm"
            return {"stage": "awaiting_confirm"}
        decision = interrupt(payload)
        approve, reason = _decision(decision)
        state.confirmed = approve
        state.confirm_reason = reason
        state.stage = "confirmed" if approve else "rejected"
        return {"confirmed": approve, "confirm_reason": reason, "stage": state.stage}

    def execute_node(state: CleanState) -> Dict[str, Any]:
        data = io.load_before() or {}
        try:
            result = execute_recipe(state, data.get("columns", []), data.get("rows", []))
        except EngineError as exc:
            state.add_error("execute", exc.message)
            return {"stage": state.stage, "errors": state.errors}
        io.save({"columns": result["columns"], "rows": result["rows"]})
        if io.store:
            for entry in result["transform_log"]:
                io.store.append_log(state.thread_id, entry.get("step", 0), entry.get("op", ""), entry)
        return {"stage": "executed", "transform_log": result["transform_log"],
                "data_ref": result["data_ref"], "errors": state.errors}

    def verify_node(state: CleanState) -> Dict[str, Any]:
        from ..verify.verifier import compare
        before = io.load_before() or {}
        after = io.load_after() or before
        result = compare(before, after, profile=state.profile)
        begin_verify_round(state, result["passed"], result["metrics"], result["unmet"])
        return {"verify": state.verify, "stage": state.stage,
                "retry_count": state.retry_count, "errors": state.errors}

    def report_node(state: CleanState) -> Dict[str, Any]:
        from ..report.reporter import build_report
        state.report = build_report(state, state.profile, state.verify, state.transform_log)
        return {"report": state.report, "stage": "reported"}

    def export_node(state: CleanState) -> Dict[str, Any]:
        # 收尾节点：校验清洗副本可读（真正落盘由 /api/export 显式触发）
        after = io.load_after()
        if after is None:
            state.add_error("export", "清洗副本不可读，导出前置校验失败")
        return {"stage": state.stage, "errors": state.errors}

    def route_after_plan(state: CleanState) -> str:
        # 计划阶段若已产生错误（缺列/未知操作/缺数据引用），不进入人工门，直接收尾
        return "confirm" if (state.rules_plan and not state.errors) else END

    def route_after_confirm(state: CleanState) -> str:
        return "execute" if state.confirmed else END

    def route_after_verify(state: CleanState) -> str:
        if state.stage == "verify_failed":  # 未超限：回人工门重确认（≤2 次）
            return "confirm"
        return "report_build"  # verified / awaiting_hitl（超限转人工，出报告留痕）

    g = StateGraph(CleanState)
    g.add_node("parse", _wrap("parse", parse_node))
    g.add_node("eda", _wrap("eda", eda_node))
    g.add_node("plan", _wrap("plan", plan_node))
    g.add_node("confirm", _wrap("confirm", confirm_node))
    g.add_node("execute", _wrap("execute", execute_node))
    g.add_node("verify_check", _wrap("verify_check", verify_node))
    g.add_node("report_build", _wrap("report_build", report_node))
    g.add_node("export", _wrap("export", export_node))
    g.add_edge(START, "parse")
    g.add_edge("parse", "eda")
    g.add_edge("eda", "plan")
    g.add_conditional_edges("plan", route_after_plan, {"confirm": "confirm", END: END})
    g.add_conditional_edges("confirm", route_after_confirm, {"execute": "execute", END: END})
    g.add_edge("execute", "verify_check")
    g.add_conditional_edges("verify_check", route_after_verify,
                            {"confirm": "confirm", "report_build": "report_build"})
    g.add_edge("report_build", "export")
    g.add_edge("export", END)
    return g.compile(checkpointer=checkpointer)
