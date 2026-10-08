"""列级操作（列级 5 项：改名 / 删列 / 拆分列 / 合并列 / 派生列）。"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import re
from typing import Any, Dict, List

from ..base import OpContext, OpResult, Operation


class ColumnRenameOp(Operation):
    op_name = "column_rename"
    level = "column"
    description = "改名：重命名一列"

    def validate(self, ctx: OpContext) -> List[str]:
        col = ctx.params.get("column")
        if not col:
            return ["未选择目标列"]
        return [] if col in ctx.columns else [f"缺少列: {col}"]

    def apply(self, ctx: OpContext) -> OpResult:
        old, new = ctx.params["column"], ctx.params["new_name"]
        new_cols = [new if c == old else c for c in ctx.columns]
        return OpResult(rows=ctx.rows, columns=new_cols, log={"op": self.op_name, "column": old, "new_name": new})

    def describe(self, params: Dict[str, Any]) -> str:
        return f"列改名 {params['column']} → {params['new_name']}"


class ColumnDeleteOp(Operation):
    op_name = "column_delete"
    level = "column"
    description = "删列：删除一列或多列"

    def validate(self, ctx: OpContext) -> List[str]:
        cols = [c for c in (ctx.params.get("columns") or [ctx.params.get("column")]) if c]
        if not cols:
            return ["未选择目标列"]
        return [f"缺少列: {c}" for c in cols if c not in ctx.columns]

    def apply(self, ctx: OpContext) -> OpResult:
        cols = set(ctx.params.get("columns") or [ctx.params.get("column")])
        idxs = [i for i, c in enumerate(ctx.columns) if c in cols]
        new_cols = [c for i, c in enumerate(ctx.columns) if i not in idxs]
        new_rows = [[v for i, v in enumerate(row) if i not in idxs] for row in ctx.rows]
        return OpResult(rows=new_rows, columns=new_cols, log={"op": self.op_name, "columns": sorted(cols)})

    def describe(self, params: Dict[str, Any]) -> str:
        return f"删除列 {params.get('columns') or params.get('column')}"


class ColumnSplitOp(Operation):
    op_name = "column_split"
    level = "column"
    description = "拆分列：按分隔符 / 正则 / 定宽拆分一列为多列"

    def validate(self, ctx: OpContext) -> List[str]:
        col = ctx.params.get("column")
        if not col:
            return ["未选择目标列"]
        return [] if col in ctx.columns else [f"缺少列: {col}"]

    def apply(self, ctx: OpContext) -> OpResult:
        col = ctx.params["column"]
        ci = ctx.columns.index(col)
        sep = ctx.params.get("separator")
        regex = ctx.params.get("regex")
        new_names = ctx.params.get("new_columns") or ["", ""]
        new_cols = ctx.columns[:ci] + list(new_names) + ctx.columns[ci + 1:]
        new_rows = []
        for row in ctx.rows:
            cell = str(row[ci]) if ci < len(row) and row[ci] is not None else ""
            if regex:
                parts = re.split(regex, cell)
            elif sep:
                parts = cell.split(sep)
            else:
                parts = [cell]
            new_rows.append(row[:ci] + parts + row[ci + 1:])
        return OpResult(rows=new_rows, columns=new_cols, log={"op": self.op_name, "column": col})

    def describe(self, params: Dict[str, Any]) -> str:
        return f"按 {'正则' if params.get('regex') else repr(params.get('separator'))} 拆分列 {params['column']}"


class ColumnMergeOp(Operation):
    op_name = "column_merge"
    level = "column"
    description = "合并列：多列按分隔符合并为一列"

    def validate(self, ctx: OpContext) -> List[str]:
        cols = [c for c in (ctx.params.get("columns") or []) if c]
        if not cols:
            return ["未选择目标列"]
        return [f"缺少列: {c}" for c in cols if c not in ctx.columns]

    def apply(self, ctx: OpContext) -> OpResult:
        cols = ctx.params["columns"]
        sep = ctx.params.get("separator", "_")
        new_name = ctx.params.get("new_name", "_".join(cols))
        idxs = [ctx.columns.index(c) for c in cols]
        new_cols = [c for i, c in enumerate(ctx.columns) if i not in idxs] + [new_name]
        new_rows = []
        for row in ctx.rows:
            merged = sep.join(str(row[i]) if i < len(row) and row[i] is not None else "" for i in idxs)
            new_rows.append([v for i, v in enumerate(row) if i not in idxs] + [merged])
        return OpResult(rows=new_rows, columns=new_cols, log={"op": self.op_name, "columns": cols})

    def describe(self, params: Dict[str, Any]) -> str:
        return f"合并列 {params['columns']} → {params.get('new_name', '_'.join(params['columns']))}"


class ColumnDeriveOp(Operation):
    op_name = "column_derive"
    level = "column"
    description = "派生列：基于表达式新建一列（支持列引用 {col} 与算术表达式）"

    def validate(self, ctx: OpContext) -> List[str]:
        expr = ctx.params.get("expression", "")
        deps = re.findall(r"\{([^{}]+)\}", expr)
        return [f"缺少列: {d}" for d in deps if d not in ctx.columns]

    def _eval_expr(self, expr: str, row: List[Any], ctx: OpContext) -> str:
        """受限表达式求值：仅支持 {col} 引用替换 + 四则运算；失败返回原样（不猜）。"""
        import ast
        import operator as op_mod

        def _replace(m):
            col = m.group(1)
            ci = ctx.columns.index(col)
            return str(row[ci]) if ci < len(row) and row[ci] is not None else "0"

        safe = re.sub(r"\{([^{}]+)\}", _replace, expr)
        try:
            tree = ast.parse(safe, mode="eval")
            binops = {ast.Add: op_mod.add, ast.Sub: op_mod.sub, ast.Mult: op_mod.mul,
                      ast.Div: op_mod.truediv, ast.FloorDiv: op_mod.floordiv, ast.Mod: op_mod.mod}
            unops = {ast.USub: op_mod.neg, ast.UAdd: op_mod.pos}

            def _eval(node):
                if isinstance(node, ast.Expression):
                    return _eval(node.body)
                if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str)):
                    return node.value
                if isinstance(node, ast.BinOp) and type(node.op) in binops:
                    return binops[type(node.op)](_eval(node.left), _eval(node.right))
                if isinstance(node, ast.UnaryOp) and type(node.op) in unops:
                    return unops[type(node.op)](_eval(node.operand))
                raise ValueError("unsupported expression")

            return str(_eval(tree))
        except Exception:
            return safe

    def apply(self, ctx: OpContext) -> OpResult:
        new_name = ctx.params["new_column"]
        expr = ctx.params.get("expression", "")
        new_cols = ctx.columns + [new_name]
        new_rows = []
        for row in ctx.rows:
            new_rows.append(row + [self._eval_expr(expr, row, ctx)])
        return OpResult(rows=new_rows, columns=new_cols, log={"op": self.op_name, "new_column": new_name})

    def describe(self, params: Dict[str, Any]) -> str:
        return f"派生列 {params['new_column']} = {params.get('expression')}"
