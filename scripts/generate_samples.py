# SPDX-License-Identifier: Apache-2.0
"""生成 samples/ 下的合成示例数据（红线：纯自造，不得由客户真实数据派生）。

产物（确定性，可重复生成）：
  samples/dirty_orders.csv         UTF-8 脏订单样例
  samples/dirty_orders_gbk.csv     GBK 编码脏订单样例（验证编码探测）
  samples/recipe_orders_demo.json  配套清洗配方（一键重放演示）
"""
from __future__ import annotations

import json
import pathlib

SAMPLES = pathlib.Path(__file__).resolve().parent.parent / "samples"

CSV_ROWS = [
    "id,名称,金额,日期,备注",
    'A001,张三,"￥1,200",2024/01/01,正常',
    'A001,张三,"￥1,200",2024/01/01,正常',
    "A002,李四,,2024-13-99,乱码\ufffd",
    "A003,王五,3000元,2024.02.30, 前后空格 ",
    "A004,Ｔｅｓｔ,５０,2024-03-15,全角数字",
    "A005,赵六,-1200,2023-12-31,负数金额",
]

# GBK 样例行：\ufffd 无法用 GBK 编码，替换为 GBK 可编码的经典乱码「锟斤拷」
GBK_ROWS = [
    "id,名称,金额,日期,备注",
    'A001,张三,"￥1,200",2024/01/01,正常',
    'A001,张三,"￥1,200",2024/01/01,正常',
    "A002,李四,,2024-13-99,锟斤拷",
    "A003,王五,3000元,2024.02.30, 前后空格 ",
    "A004,Ｔｅｓｔ,５０,2024-03-15,全角数字",
    "A005,赵六,-1200,2023-12-31,负数金额",
]

RECIPE = {
    "schema_id": "clean-recipe/v1",
    "name": "orders-demo",
    "source": {"thread_id": "demo", "file_name": "dirty_orders.csv"},
    "operations": [
        {"op": "row_dedupe", "params": {}},
        {"op": "cell_trim", "params": {"columns": ["备注"]}},
        {"op": "cell_amount_clean", "params": {"column": "金额"}},
        {"op": "cell_date_normalize", "params": {"column": "日期"}},
        {"op": "cell_fullwidth", "params": {"columns": ["名称"]}},
    ],
}


def main() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    utf8 = "\n".join(CSV_ROWS) + "\n"
    (SAMPLES / "dirty_orders.csv").write_text(utf8, encoding="utf-8")
    gbk = "\n".join(GBK_ROWS) + "\n"
    (SAMPLES / "dirty_orders_gbk.csv").write_text(gbk, encoding="gbk")
    (SAMPLES / "recipe_orders_demo.json").write_text(
        json.dumps(RECIPE, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("samples regenerated: dirty_orders.csv / dirty_orders_gbk.csv / recipe_orders_demo.json")


if __name__ == "__main__":
    main()
