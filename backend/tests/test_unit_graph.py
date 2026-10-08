# SPDX-License-Identifier: Apache-2.0
"""L1 单元测试：LangGraph 编排图。

覆盖：8 节点拓扑 / 节点名与状态键撞名回归 / HITL 人工门中断（execute 前，confirm 节点
动态 interrupt）/ 中断恢复继续执行 / 状态推进（parsed → eda → awaiting_confirm → executed）。
"""

from app.graph.pipeline import NODE_ORDER, NODE_STATE_KEY, GraphIO, build_pipeline
from app.state import CleanState

COLS = ["id", "金额"]
# 10 行含 1 行完全重复：去重后 9 行（减少 10%，未触发「行数塌缩 >30%」判定）
ROWS = [[f"A{i:03d}", "￥1,200"] for i in range(1, 10)] + [["A001", "￥1,200"]]
# 清洗副本题材（row_dedupe + cell_amount_clean 之后的期望结果）
ROWS_AFTER = [[f"A{i:03d}", "1200"] for i in range(1, 10)]

RECIPE_OPS = [
    {"op": "row_dedupe", "params": {}},
    {"op": "cell_amount_clean", "params": {"column": "金额"}},
]


class DummyIO:
    def __init__(self):
        self.saved = None
        self.before = {"columns": COLS, "rows": ROWS}

    def load_before(self):
        return self.before

    def load(self):
        return {"columns": COLS, "rows": ROWS}

    def load_after(self):
        """清洗副本（execute 落盘后的回读视图）：模拟去重 + 金额清洗后的结果。"""
        return {"columns": COLS, "rows": ROWS_AFTER}

    def save(self, data):
        self.saved = data


def test_build_pipeline_nodes():
    g = build_pipeline(GraphIO(DummyIO().load_before, DummyIO().save))
    # 图对象含节点名（verify_check / report_build 为避让状态键后的节点名）
    for n in ("parse", "eda", "plan", "confirm", "execute", "verify_check", "report_build", "export"):
        assert n in g.nodes
    assert set(NODE_ORDER) == {"parse", "eda", "plan", "confirm", "execute",
                               "verify_check", "report_build", "export"}


def test_node_names_never_collide_with_state_keys():
    """回归：节点名与状态键同名时 build_pipeline 会抛
    ValueError: '<name>' is already being used as a state key。"""
    state_keys = set(CleanState.model_fields)
    assert {"verify", "report"} <= state_keys  # 状态键为既有字段名，不可改名
    assert not (set(NODE_ORDER) & state_keys)
    assert NODE_STATE_KEY == {"verify_check": "verify", "report_build": "report"}
    build_pipeline(GraphIO(DummyIO().load_before, DummyIO().save))  # 构建不得抛 ValueError


def test_pipeline_interrupts_before_execute():
    io = DummyIO()
    g = build_pipeline(GraphIO(io.load_before, io.save))
    state = CleanState(thread_id="t", source={"file_name": "s.csv"},
                       data_ref="ref://orders.csv",
                       rules_plan={"schema_id": "clean-recipe/v1", "operations": RECIPE_OPS})
    result = g.invoke(state)
    # 人工门在 execute 前：无检查点时不挂起，仅标注待确认（不得误判为已确认）
    assert result["stage"] == "awaiting_confirm"
    assert result.get("confirmed", False) is False


def test_pipeline_resume_to_executed():
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import Command

    io = DummyIO()
    g = build_pipeline(GraphIO(io.load_before, io.save, load_after_fn=io.load_after),
                       checkpointer=MemorySaver())
    state = CleanState(thread_id="t", source={"file_name": "s.csv"},
                       data_ref="ref://orders.csv", confirmed=True,
                       rules_plan={"schema_id": "clean-recipe/v1", "operations": RECIPE_OPS})
    cfg = {"configurable": {"thread_id": "t"}}
    first = g.invoke(state, cfg)
    assert first["stage"] == "awaiting_confirm"
    # 恢复执行（中断后继续），用 Command(resume=...) 注入确认结果
    resumed = g.invoke(Command(resume=True), cfg)
    assert resumed["stage"] in ("executed", "verify_failed", "verified", "reported", "done")
    assert io.saved is not None  # execute 已写清洗副本


def test_pipeline_parse_requires_data_ref():
    io = DummyIO()
    g = build_pipeline(GraphIO(io.load_before, io.save))
    state = CleanState(thread_id="t", source={"file_name": "s.csv"})
    result = g.invoke(state)
    assert "errors" in result
