# SPDX-License-Identifier: Apache-2.0
"""L1 单元测试：操作库（行级3 + 列级5 + 单元格级8）。

每个操作 = apply / validate / describe；注册表登记。
"""

from app.operations.base import OpContext, OperationRegistry

COLS = ["id", "金额", "日期", "单位", "备注"]
ROWS = [
    ["A001", "￥1,200", "2024/01/01", "MPa", "  正常  "],
    ["A001", "￥1,200", "2024/01/01", "MPa", "  正常  "],
    ["A002", None, "2024-13-99", "bar", "乱码��"],
    ["A003", "3000元", "2024.02.30", "kg", "Text"],
]


def run_op(op_name: str, params: dict):
    cls = OperationRegistry.get(op_name)
    assert cls is not None, f"{op_name} 未注册"
    op = cls()
    ctx = OpContext(columns=COLS, rows=[list(r) for r in ROWS], params=params)
    errors = op.validate(ctx)
    assert errors == [], f"{op_name} validate: {errors}"
    result = op.apply(ctx)
    assert result.ok
    assert isinstance(op.describe(params), str)
    return result


EXPECTED_OPS = {
    # 行级 3
    "row_dedupe", "row_delete", "row_keep",
    # 列级 5
    "column_rename", "column_delete", "column_split", "column_merge", "column_derive",
    # 单元格级 8
    "cell_trim", "cell_fullwidth", "cell_unit_convert", "cell_case",
    "cell_date_normalize", "cell_amount_clean", "cell_text_replace", "cell_fill_missing",
}


def test_registry_has_16():
    assert set(OperationRegistry.all().keys()) == EXPECTED_OPS


# --- 行级 ---------------------------------------------------------------
def test_row_dedupe():
    r = run_op("row_dedupe", {})
    assert len(r.rows) == 3
    assert r.log["rows_affected"] == 1


def test_row_dedupe_subset():
    r = run_op("row_dedupe", {"subset": ["id"]})
    assert len(r.rows) == 3


def test_row_delete():
    r = run_op("row_delete", {"column": "id", "value": "A002"})
    assert len(r.rows) == 3
    assert r.log["rows_affected"] == 1


def test_row_delete_missing_column_validate():
    cls = OperationRegistry.get("row_delete")
    ctx = OpContext(columns=COLS, rows=[], params={"column": "不存在"})
    assert cls().validate(ctx) != []


def test_row_keep():
    r = run_op("row_keep", {"column": "id", "value": "A001"})
    assert len(r.rows) == 2


# --- 列级 ---------------------------------------------------------------
def test_column_rename():
    r = run_op("column_rename", {"column": "金额", "new_name": "金额_clean"})
    assert "金额_clean" in r.columns and "金额" not in r.columns


def test_column_delete():
    r = run_op("column_delete", {"columns": ["备注"]})
    assert "备注" not in r.columns
    assert all(len(row) == 4 for row in r.rows)


def test_column_split_separator():
    r = run_op("column_split", {"column": "日期", "separator": "/", "new_columns": ["y", "m", "d"]})
    assert "y" in r.columns
    assert r.rows[0][r.columns.index("y")] == "2024"


def test_column_split_regex():
    r = run_op("column_split", {"column": "备注", "regex": r"(\s+)", "new_columns": ["a", "b"]})
    assert r.columns[r.columns.index("a")] == "a"


def test_column_merge():
    r = run_op("column_merge", {"columns": ["id", "备注"], "separator": "-", "new_name": "merged"})
    assert "merged" in r.columns
    assert r.rows[0][-1] == "A001-  正常  "


def test_column_derive():
    from app.operations.base import OpContext, OperationRegistry

    cls = OperationRegistry.get("column_derive")
    ctx = OpContext(columns=["a", "b"], rows=[["5", "3"]], params={"new_column": "sum", "expression": "{a}*2+{b}"})
    r = cls().apply(ctx)
    assert r.columns == ["a", "b", "sum"]
    assert r.rows[0][2] == "13"


def test_column_derive_non_numeric_kept_as_is():
    from app.operations.base import OpContext, OperationRegistry

    cls = OperationRegistry.get("column_derive")
    ctx = OpContext(columns=["金额"], rows=[["￥1,200"]], params={"new_column": "x", "expression": "{金额}*2"})
    r = cls().apply(ctx)
    assert r.rows[0][1] == "￥1,200*2"  # 求值失败原样返回（不猜、不编造）


def test_column_derive_missing_dep_validate():
    cls = OperationRegistry.get("column_derive")
    ctx = OpContext(columns=COLS, rows=[], params={"new_column": "x", "expression": "{不存在}+1"})
    assert cls().validate(ctx) != []


# --- 单元格级 ------------------------------------------------------------
def test_cell_trim():
    r = run_op("cell_trim", {"columns": ["备注"]})
    assert r.rows[0][COLS.index("备注")] == "正常"


def test_cell_fullwidth():
    from app.operations.base import OpContext, OperationRegistry

    cls = OperationRegistry.get("cell_fullwidth")
    ctx = OpContext(columns=["备注"], rows=[["ＡＢＣ１２３"], ["正常"], ["Ｔｅｓｔ"], ["ａｂｃ"]],
                    params={"columns": ["备注"]})
    r = cls().apply(ctx)
    assert r.rows[0][0] == "ABC123"      # 全角数字字母转半角
    assert r.rows[1][0] == "正常"          # 汉字不受影响
    assert r.rows[2][0] == "Test"        # 全角小写字母同样转半角（回归：曾漏映射 ａ-ｚ）
    assert r.rows[3][0] == "abc"


def test_cell_unit_convert():
    from app.operations.base import OpContext, OperationRegistry

    cls = OperationRegistry.get("cell_unit_convert")
    ctx = OpContext(columns=["单位"], rows=[["1 MPa"], ["2 MPa"]],
                    params={"column": "单位", "from": "MPa", "to": "bar"})
    r = cls().apply(ctx)
    assert r.rows[0][0] == 10.0
    assert r.rows[1][0] == 20.0


def test_cell_unit_convert_unsupported_validate():
    cls = OperationRegistry.get("cell_unit_convert")
    ctx = OpContext(columns=COLS, rows=[], params={"column": "单位", "from": "xx", "to": "yy"})
    assert cls().validate(ctx) != []


def test_cell_case():
    r = run_op("cell_case", {"columns": ["备注"], "mode": "upper"})
    assert r.rows[3][COLS.index("备注")] == "TEXT"


def test_cell_date_normalize():
    r = run_op("cell_date_normalize", {"column": "日期"})
    assert r.rows[0][COLS.index("日期")] == "2024-01-01"


def test_cell_amount_clean():
    """金额清洗：去货币前后缀 / 千分位 / 全角，统一纯数字（小数位口径对齐）。"""
    r = run_op("cell_amount_clean", {"column": "金额"})
    assert r.rows[0][COLS.index("金额")] == "1200"      # ￥1,200 → 1200（整数不带小数位）
    assert r.rows[3][COLS.index("金额")] == "3000"      # 3000元 → 3000（中文后缀）


def test_cell_amount_clean_currency_table():
    """货币符号表 + 全角 + 括号负数 + 千分位。"""
    from app.operations.data.currency_affixes import clean_amount

    assert clean_amount("1,299.00元") == "1299.00"
    assert clean_amount("RMB 4055.14") == "4055.14"
    assert clean_amount("￥1,200") == "1200"
    assert clean_amount("(1200)") == "-1200"
    assert clean_amount("１２３４") == "1234"
    assert clean_amount("¥ 4,334.41") == "4334.41"
    assert clean_amount("人民币 88 元") == "88"
    # 量级 / 子单位不剥离：数值会被篡改，一律登记未处理
    assert clean_amount("1万元") is None
    assert clean_amount("50分") is None
    # 无法解析 → None（调用方保留原值 + 登记），不猜不洗
    assert clean_amount("待补") is None
    assert clean_amount("1,2,3") is None


def test_cell_amount_clean_unresolved_kept():
    """不可解析值保留原值并登记未处理，不得静默置空。"""
    ctx = OpContext(columns=["id", "金额"], rows=[["X", "待补"], ["Y", "面议"], ["Z", "1,2,3"]],
                    params={"column": "金额"})
    op = OperationRegistry.get("cell_amount_clean")()
    result = op.apply(ctx)
    assert [row[1] for row in result.rows] == ["待补", "面议", "1,2,3"]
    assert result.log["unresolved_count"] == 3
    assert result.log["unresolved_samples"] == ["待补", "面议", "1,2,3"]
    assert "未处理" in result.log["unresolved_reason"] or "保留原值" in result.log["unresolved_reason"]


def test_cell_date_normalize_compact_and_illegal():
    """支持 YYYYMMDD / 多分隔符；非法日期保留原值并登记。"""
    ctx = OpContext(
        columns=["id", "日期"],
        rows=[["A", "20240808"], ["B", "2024/5/6"], ["C", "2024.05.06"], ["D", "2024年1月18日"],
              ["E", "2024-02-30"], ["F", "2024-13-99"], ["G", "2024-01-18"]],
        params={"column": "日期"},
    )
    result = OperationRegistry.get("cell_date_normalize")().apply(ctx)
    col = 1
    assert result.rows[0][col] == "2024-08-08"
    assert result.rows[1][col] == "2024-05-06"
    assert result.rows[2][col] == "2024-05-06"
    assert result.rows[3][col] == "2024-01-18"
    assert result.rows[4][col] == "2024-02-30"   # 非法 → 原样保留
    assert result.rows[5][col] == "2024-13-99"
    assert result.log["unresolved_count"] == 2
    assert result.rows[6][col] == "2024-01-18"   # 已规范值走快路径，不重复改写


def test_cell_unit_convert_identity():
    """联动：同单位换算（元→元）放行，不再"提交即报错"。"""
    ctx = OpContext(columns=["id", "金额"], rows=[["A", "1200"], ["B", "3000"]],
                    params={"column": "金额", "from": "元", "to": "元"})
    op = OperationRegistry.get("cell_unit_convert")()
    assert op.validate(ctx) == []
    result = op.apply(ctx)
    assert result.ok
    assert [row[1] for row in result.rows] == [1200.0, 3000.0]
    assert "同单位" in op.describe(ctx.params)


def test_cell_unit_convert_strip_units():
    """联动：目标单位填「纯数值」→ 剥离模式，取前导数值（`3件`→3、`5台`→5）。

    剥离模式不查换算表（量词之间本无换算对），也不校验 `from` 是否出现；非数字开头的值原样保留。
    """
    ctx = OpContext(columns=["id", "数量"], rows=[["A", "3件"], ["B", "2"], ["C", "5台"], ["D", "N/A"]],
                    params={"column": "数量", "from": "件", "to": "纯数值"})
    op = OperationRegistry.get("cell_unit_convert")()
    assert op.validate(ctx) == []
    result = op.apply(ctx)
    assert result.ok
    assert [row[1] for row in result.rows] == [3, 2, 5, "N/A"]
    assert result.log["mode"] == "strip"
    assert "纯数值" in op.describe(ctx.params)


def test_cell_unit_convert_strip_validate_no_conversion_table():
    """剥离模式不查换算表：即便 `from` 不在表内（如 `件`）也放行，不再「提交即报错」。"""
    ctx = OpContext(columns=["数量"], rows=[["3件"]],
                    params={"column": "数量", "from": "件", "to": "数值"})
    op = OperationRegistry.get("cell_unit_convert")()
    assert op.validate(ctx) == []


def test_cell_unit_convert_strip_keeps_non_count_units():
    """反例：非计数单位后缀**不剥离**，保留原值 + 计数披露，不静默。

    `2kg` / `10元` / `1.5万元` 剥离后语义会变（`2` ≠ `2kg`），故一律原值保留并计入
    `log.skipped_non_count`；`describe()` 如实写明该口径。
    """
    ctx = OpContext(columns=["id", "数量"],
                    rows=[["A", "2kg"], ["B", "10元"], ["C", "1.5万元"], ["D", "3件"], ["E", "5"]],
                    params={"column": "数量", "from": "件", "to": "纯数值"})
    op = OperationRegistry.get("cell_unit_convert")()
    assert op.validate(ctx) == []
    result = op.apply(ctx)
    assert result.ok
    assert [row[1] for row in result.rows] == ["2kg", "10元", "1.5万元", 3, 5]
    assert result.log["mode"] == "strip"
    assert result.log["skipped_non_count"] == 3
    assert result.log["skipped_non_samples"] == ["2kg", "10元", "1.5万元"]
    assert result.log["skipped_non_reason"]
    desc = op.describe(ctx.params)
    assert "非计数单位" in desc and "保留原值" in desc


def test_cell_unit_convert_strip_count_units_positive_and_boundary():
    """正例 / 边界：`3件`→3、`100 件`（含空格）→100、`3件装`（词表内多字量词）→3、
    纯数字 `5` 放行、英文量词 `PCS` 与带符号值同样生效；无跳过项时计数为 0。"""
    ctx = OpContext(columns=["数量"],
                    rows=[["3件"], ["100 件"], ["3件装"], ["5"], ["+2PCS"], ["-1 个"]],
                    params={"column": "数量", "from": "件", "to": "纯数值"})
    op = OperationRegistry.get("cell_unit_convert")()
    assert op.validate(ctx) == []
    result = op.apply(ctx)
    assert [row[0] for row in result.rows] == [3, 100, 3, 5, 2, -1]
    assert result.log["skipped_non_count"] == 0


def test_cell_unit_convert_convert_path_unchanged():
    """范围约束：非剥离路径语义不变（换算照常、「不在换算表即拦截」照常）。"""
    ctx = OpContext(columns=["数量"], rows=[["1kg"], ["2"], ["x"]],
                    params={"column": "数量", "from": "kg", "to": "g"})
    op = OperationRegistry.get("cell_unit_convert")()
    assert op.validate(ctx) == []
    result = op.apply(ctx)
    assert [row[0] for row in result.rows] == [1000.0, 2000.0, "x"]
    assert result.log["mode"] == "convert"
    assert result.log["skipped_non_count"] == 0
    # validate 前置拦截语义不变（`件`→`g` 不在内置换算表）
    bad = OpContext(columns=["数量"], rows=[["3件"]], params={"column": "数量", "from": "件", "to": "g"})
    errors = op.validate(bad)
    assert len(errors) == 1 and "不支持的单位换算" in errors[0]


def test_cell_text_replace():
    r = run_op("cell_text_replace", {"columns": ["备注"], "old": "乱码", "new": "修复"})
    assert r.rows[2][COLS.index("备注")] == "修复��"


def test_cell_text_replace_regex():
    r = run_op("cell_text_replace", {"columns": ["备注"], "old": r"\s+", "new": "_", "regex": True})
    assert r.rows[0][COLS.index("备注")] == "_正常_"


def test_cell_fill_missing_constant():
    r = run_op("cell_fill_missing", {"column": "金额", "method": "constant", "value": "N/A"})
    assert r.rows[2][COLS.index("金额")] == "N/A"


def test_cell_fill_missing_mean():
    r = run_op("cell_fill_missing", {"column": "金额", "method": "mean"})
    assert r.rows[2][COLS.index("金额")] is not None


def test_unknown_op_not_registered():
    assert not OperationRegistry.is_known("no_such_op")
