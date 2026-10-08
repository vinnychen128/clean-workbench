"""行级操作（行级 3 项）。"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Any, Dict, List

from ..base import OpContext, OpResult, Operation


class RowDedupeOp(Operation):
    op_name = "row_dedupe"
    level = "row"
    description = "去重：按指定列子集（默认全列）去重复行"

    def validate(self, ctx: OpContext) -> List[str]:
        subset = ctx.params.get("subset") or []
        missing = [c for c in subset if c and c not in ctx.columns]
        return [f"缺少列: {c}" for c in missing]

    def apply(self, ctx: OpContext) -> OpResult:
        subset = ctx.params.get("subset") or []
        keep = ctx.params.get("keep", "first")
        idxs = [ctx.columns.index(c) for c in subset] if subset else list(range(len(ctx.columns)))
        seen = set()
        new_rows: List[List[Any]] = []
        affected = 0
        sample_before = None
        for row in ctx.rows:
            key = tuple(str(row[i]) if i < len(row) else "" for i in idxs)
            if key in seen:
                if keep == "first":
                    affected += 1
                    sample_before = row
                    continue
            else:
                seen.add(key)
                new_rows.append(row)
        return OpResult(
            rows=new_rows,
            columns=ctx.columns,
            log={"op": self.op_name, "rows_affected": affected, "sample_before": sample_before},
        )

    def describe(self, params: Dict[str, Any]) -> str:
        return f"按 {params.get('subset') or '全列'} 去重（保留{params.get('keep', 'first')}）"


class RowDeleteOp(Operation):
    op_name = "row_delete"
    level = "row"
    description = "删行：删除满足条件的行（where 为单元格值精确匹配，支持空值）"

    def validate(self, ctx: OpContext) -> List[str]:
        col = ctx.params.get("column")
        if not col:
            return ["未选择目标列"]
        if col not in ctx.columns:
            return [f"缺少列: {col}"]
        return []

    def apply(self, ctx: OpContext) -> OpResult:
        col = ctx.params.get("column")
        value = ctx.params.get("value")
        new_rows: List[List[Any]] = []
        affected = 0
        sample_before = None
        ci = ctx.columns.index(col) if col else None
        for row in ctx.rows:
            cell = row[ci] if ci is not None and ci < len(row) else None
            match = (cell is None and value is None) or (str(cell) == str(value))
            if match:
                affected += 1
                sample_before = row
            else:
                new_rows.append(row)
        return OpResult(
            rows=new_rows,
            columns=ctx.columns,
            log={"op": self.op_name, "rows_affected": affected, "sample_before": sample_before},
        )

    def describe(self, params: Dict[str, Any]) -> str:
        return f"删除 {params.get('column')} = {params.get('value')} 的行"


class RowKeepOp(Operation):
    op_name = "row_keep"
    level = "row"
    description = "保行：仅保留满足条件的行"

    def validate(self, ctx: OpContext) -> List[str]:
        col = ctx.params.get("column")
        if not col:
            return ["未选择目标列"]
        if col not in ctx.columns:
            return [f"缺少列: {col}"]
        return []

    def apply(self, ctx: OpContext) -> OpResult:
        col = ctx.params.get("column")
        value = ctx.params.get("value")
        new_rows: List[List[Any]] = []
        affected = 0
        ci = ctx.columns.index(col) if col else None
        for row in ctx.rows:
            cell = row[ci] if ci is not None and ci < len(row) else None
            if (cell is None and value is None) or (str(cell) == str(value)):
                new_rows.append(row)
            else:
                affected += 1
        return OpResult(
            rows=new_rows,
            columns=ctx.columns,
            log={"op": self.op_name, "rows_affected": affected, "sample_before": None},
        )

    def describe(self, params: Dict[str, Any]) -> str:
        return f"仅保留 {params.get('column')} = {params.get('value')} 的行"
