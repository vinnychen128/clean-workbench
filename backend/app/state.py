"""清洗项目 · 运行状态数据契约（CleanState）。

运行状态字段契约：入口字段只读；输出字段各节点写自己的；errors 全节点累加。
"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CleanState(BaseModel):
    """LangGraph 全程传递的共享状态（大对象不进状态，只存引用）。"""

    # 入口（写，之后只读）
    thread_id: str = Field(..., description="运行线程标识 clean-<日期>-<哈希>")
    source: Dict[str, Any] = Field(default_factory=dict, description="原文件元信息（只读）")

    # 阶段化数据引用：解析后=对原件的只读引用；执行后=清洗副本的路径引用
    data_ref: Optional[str] = None

    # 各节点输出
    profile: Dict[str, Any] = Field(default_factory=dict, description="体检结果 issues/分数/严重度")
    rules_plan: Dict[str, Any] = Field(default_factory=dict, description="配方（有序操作清单）")
    recipe_id: Optional[str] = None
    transform_log: List[Dict[str, Any]] = Field(default_factory=list, description="转换日志（追加）")
    signature_check: Dict[str, Any] = Field(
        default_factory=dict, description="配方签名校验结果（执行前，防篡改）"
    )
    verify: Dict[str, Any] = Field(default_factory=dict, description="前后对比指标")
    report: Dict[str, Any] = Field(default_factory=dict, description="三段式报告")
    stage: str = Field(default="idle", description="当前阶段（供进度显示）")
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="异常收集（全节点累加）")

    # 人工门
    confirmed: bool = Field(default=False, description="配方是否已人工确认（未确认不执行）")
    confirm_reason: Optional[str] = None

    # 校验回退计数（≤2）
    retry_count: int = 0

    # 覆盖校验的越权放行留痕（ack 后放行，报告未处理项须标「经用户确认未处理」）
    overrides: Dict[str, Any] = Field(default_factory=dict, description="覆盖校验越权放行记录（ack/reason/at/uncovered）")

    def add_error(self, node: str, message: str) -> None:
        self.errors.append({"node": node, "message": message})


# 节点执行表状态枚举（7.4）
EXEC_STATUS = ("PENDING", "RUNNING", "COMPLETED", "FAILED", "AWAITING_HITL")
