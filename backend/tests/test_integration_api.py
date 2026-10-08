# SPDX-License-Identifier: Apache-2.0
"""L2 集成测试：12 条 HTTP 接口（server）。

覆盖接口：/api/health /api/eda /api/clean /api/parse /api/plan /api/confirm
/api/execute /api/verify /api/report /api/export /api/run/{run_id} /api/recipe-import。

对每个接口：正常路径 + 关键异常分支（fail-loud，错误统一 {ok:false,error:{code,message}}）。
"""
import base64
import io
import os
import re


CSV_SAMPLE = "订单号,客户,金额,备注\n10001,张三,100.5,ok\n10001,张三,100.5,ok\n10002,李四,,缺金额\n10003,王五,99999,异常"
CSV_LONG_NUM = "订单号,客户\n6222021234567890123,张三\n10002,李四\n"


def b64(text_or_bytes: bytes | str) -> str:
    if isinstance(text_or_bytes, str):
        text_or_bytes = text_or_bytes.encode("utf-8")
    return base64.b64encode(text_or_bytes).decode()


def do_parse(client, content=CSV_SAMPLE, name="orders.csv", ftype="csv", size=None, hash_=""):
    raw = content.encode("utf-8") if isinstance(content, str) else content
    resp = client.post("/api/parse", json={
        "file_name": name, "file_type": ftype, "file_size": size if size is not None else len(raw),
        "file_hash": hash_, "content_b64": b64(raw),
    })
    return resp


def parse_tid(client, content=CSV_SAMPLE, name="orders.csv"):
    resp = do_parse(client, content=content, name=name)
    assert resp.status_code == 200, resp.text
    return resp.json()["thread_id"]


def plan_tid(client, tid, ops=None, name="auto-plan"):
    ops = ops if ops is not None else [{"op": "row_dedupe", "params": {"subset": ["订单号"]}}]
    resp = client.post("/api/plan", json={"thread_id": tid, "operations": ops, "recipe_name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()


def confirm_execute(client, tid, approve=True):
    """确认 + 执行。

    覆盖校验下沉到后端后，**直调 `/api/confirm {approve:true}` 在存在未覆盖高危项时必须 409**；
    本helper 先用直调探一次（断言硬门生效），再带越权确认（如实填说明）完成确认 ——
    其余用例因此都在"有留痕"的路径上跑，且每条用例都顺带验证了硬门。
    """
    resp = client.post("/api/confirm", json={"thread_id": tid, "approve": approve, "reason": "pytest"})
    if resp.status_code == 409:
        detail = resp.json()["detail"]
        assert detail["code"] == "COVERAGE_BLOCKED", detail
        resp = client.post("/api/confirm", json={
            "thread_id": tid, "approve": approve, "reason": "pytest",
            "override": {"ack": True, "note": "用例说明：已知情跳过未覆盖高危项（本条用例非覆盖校验本身）"},
        })
    assert resp.status_code == 200, resp.text
    resp = client.post("/api/execute", json={"thread_id": tid})
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# /api/health
# ---------------------------------------------------------------------------


def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["schema_id"] == "clean-recipe/v1"
    assert re.fullmatch(r"\d+\.\d+\.\d+", body["version"])


# ---------------------------------------------------------------------------
# /api/parse
# ---------------------------------------------------------------------------


def test_parse_csv_ok(client):
    r = do_parse(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["columns"] == ["订单号", "客户", "金额", "备注"]
    assert body["row_count"] == 4
    assert body["col_count"] == 4
    assert body["parsing_report"]["encoding"] in ("utf-8", "gbk")
    assert body["thread_id"].startswith("clean-")


def test_parse_reject_unsupported_type(client):
    r = do_parse(client, name="evil.exe", ftype="exe")
    assert r.status_code == 400
    assert "仅支持 CSV / Excel / PDF" in r.json()["detail"]


def test_parse_reject_empty_file(client):
    r = do_parse(client, content="", size=0)
    assert r.status_code == 400
    assert "空文件" in r.json()["detail"]


def test_parse_reject_too_large(client):
    r = do_parse(client, size=51 * 1024 * 1024)
    assert r.status_code == 400
    assert "50MB" in r.json()["detail"]


def test_parse_gbk_csv_ok(client):
    raw = "订单号,客户,金额\n10001,张三,88\n10002,李四,99\n".encode("gbk")
    r = do_parse(client, content=raw)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["columns"] == ["订单号", "客户", "金额"]  # 中文列名不乱码
    assert body["parsing_report"]["encoding"] == "gbk"


def test_parse_long_number_kept_text(client):
    r = do_parse(client, content=CSV_LONG_NUM)
    assert r.status_code == 200, r.text
    body = r.json()
    # CSV 场景：未加引号的长数字按文本读取，无精度损失，不触发「长数字」警告
    # （该警告为 Excel/数值语义，逐单元格断言由 L1 test_unit_parsing 覆盖）
    assert body["parsing_report"]["encoding"] == "utf-8"
    assert "长数字" not in " ".join(str(w) for w in body["parsing_report"].get("warnings", []))


def test_parse_xlsx_ok(client):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["订单号", "客户", "金额"])
    ws.append(["10001", "张三", 88.5])
    ws.append(["10002", "李四", 99.5])
    buf = io.BytesIO()
    wb.save(buf)
    raw = buf.getvalue()
    r = do_parse(client, content=raw, name="orders.xlsx", ftype="xlsx")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["columns"] == ["订单号", "客户", "金额"]
    assert body["row_count"] == 2


# ---------------------------------------------------------------------------
# /api/eda
# ---------------------------------------------------------------------------


def test_eda_ok_nine_detectors(client):
    tid = parse_tid(client)
    r = client.post("/api/eda", json={"thread_id": tid})
    assert r.status_code == 200, r.text
    issues = r.json()["profile"]["issues"]
    assert len(issues) == 9
    names = {i["issue_name"] for i in issues}
    assert names == {"null", "duplicate", "outlier", "format", "amount", "date",
                     "unit", "identifier_column", "mojibake"}


def test_eda_without_parse_400(client):
    r = client.post("/api/eda", json={"thread_id": "clean-no-such"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# /api/plan
# ---------------------------------------------------------------------------


def test_plan_ok_with_steps(client):
    tid = parse_tid(client)
    body = plan_tid(client, tid, ops=[
        {"op": "row_dedupe", "params": {"subset": ["订单号"]}},
        {"op": "cell_fill_missing", "params": {"column": "备注", "method": "constant", "value": "无"}},
    ])
    assert len(body["steps"]) == 2
    assert body["steps"][0]["op"] == "row_dedupe"
    assert body["description"], "配方描述不得为空"
    assert isinstance(body["risk_flags"], list)
    # dependencies / new_columns 已随 plan 返回
    assert isinstance(body["dependencies"], list) and body["dependencies"], "依赖源列不得为空"
    assert len(body["dependencies"]) == len(set(body["dependencies"])), "依赖源列须去重"
    assert body["dependencies"] == ["订单号", "备注"], "依赖源列按配方出现顺序返回"
    assert isinstance(body["new_columns"], list)
    # 同行去重 + 补齐缺失值不产生派生列
    assert body["new_columns"] == []


def test_plan_missing_column_rejected(client):
    tid = parse_tid(client)
    r = client.post("/api/plan", json={"thread_id": tid, "operations": [
        {"op": "cell_unit_convert", "params": {"column": "压力", "from_unit": "MPa", "to_unit": "bar"}},
    ]})
    assert r.status_code == 400
    assert "压力" in r.json()["detail"]  # 缺列执行前即提示不可跑


# ---------------------------------------------------------------------------
# /api/confirm
# ---------------------------------------------------------------------------


def test_confirm_approve(client):
    tid = parse_tid(client)
    plan_tid(client, tid)
    # 本样本含未覆盖高危项（空值等），直调先被硬门拦住
    blocked = client.post("/api/confirm", json={"thread_id": tid, "approve": True, "reason": "ok"})
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"]["code"] == "COVERAGE_BLOCKED"
    r = client.post("/api/confirm", json={
        "thread_id": tid, "approve": True, "reason": "ok",
        "override": {"ack": True, "note": "用例说明：已知情跳过未覆盖高危项，本条验证确认门语义"},
    })
    assert r.status_code == 200, r.text
    assert r.json()["confirmed"] is True
    assert r.json()["stage"] == "confirmed"
    assert r.json()["override"]["ack"] is True  # 响应回显 override 留痕


def test_confirm_override_requires_note(client):
    """越权放行不得空放行 —— ack=true 但说明不足 5 字仍被 409 拦住。"""
    tid = parse_tid(client)
    plan_tid(client, tid)
    r = client.post("/api/confirm", json={"thread_id": tid, "approve": True,
                                          "override": {"ack": True, "note": "ok"}})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "OVERRIDE_NOTE_REQUIRED"


def test_confirm_reject(client):
    tid = parse_tid(client)
    plan_tid(client, tid)
    r = client.post("/api/confirm", json={"thread_id": tid, "approve": False, "reason": "取消"})
    assert r.status_code == 200
    assert r.json()["confirmed"] is False
    assert r.json()["stage"] == "rejected"


def test_confirm_without_plan_409(client):
    tid = parse_tid(client)
    r = client.post("/api/confirm", json={"thread_id": tid, "approve": True})
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# /api/execute
# ---------------------------------------------------------------------------


def test_execute_before_confirm_409(client):
    tid = parse_tid(client)
    plan_tid(client, tid)
    r = client.post("/api/execute", json={"thread_id": tid})
    assert r.status_code == 409  # 未确认不执行（红队）


def test_execute_after_confirm_ok(client):
    tid = parse_tid(client)
    plan_tid(client, tid)
    body = confirm_execute(client, tid)
    assert body["columns"] == ["订单号", "客户", "金额", "备注"]
    assert len(body["rows"]) == 3  # 去重 1 行
    assert any(item["op"] == "row_dedupe" and item["rows_affected"] >= 1 for item in body["transform_log"])


def test_execute_without_parse_400(client):
    r = client.post("/api/execute", json={"thread_id": "clean-no-such"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# /api/verify
# ---------------------------------------------------------------------------


def test_verify_before_execute_400(client):
    tid = parse_tid(client)
    r = client.post("/api/verify", json={"thread_id": tid})
    assert r.status_code == 400


def test_verify_after_execute_ok(client):
    tid = parse_tid(client)
    plan_tid(client, tid)
    confirm_execute(client, tid)
    r = client.post("/api/verify", json={"thread_id": tid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "metrics" in body and "passed" in body
    assert body["metrics"]["rows"]["after"] == 3


# ---------------------------------------------------------------------------
# /api/report
# ---------------------------------------------------------------------------


def test_report_json_ok(client):
    tid = parse_tid(client)
    plan_tid(client, tid)
    confirm_execute(client, tid)
    client.post("/api/verify", json={"thread_id": tid})
    r = client.post("/api/report", json={"thread_id": tid, "format": "json"})
    assert r.status_code == 200, r.text
    assert r.json()["format"] == "json"
    assert set(r.json()["content"]["sections"].keys()) == {"1_profile", "2_process", "3_quality", "4_unhandled"}


def test_report_md_ok(client):
    tid = parse_tid(client)
    plan_tid(client, tid)
    confirm_execute(client, tid)
    client.post("/api/verify", json={"thread_id": tid})
    r = client.post("/api/report", json={"thread_id": tid, "format": "md"})
    assert r.status_code == 200
    assert "# 清洗报告" in r.json()["content"]
    assert "## 一、" in r.json()["content"]


# ---------------------------------------------------------------------------
# /api/export
# ---------------------------------------------------------------------------


def test_export_before_execute_400(client):
    tid = parse_tid(client)
    r = client.post("/api/export", json={"thread_id": tid, "format": "xlsx"})
    assert r.status_code == 400


def test_export_xlsx_ok(client, tmp_path):
    tid = parse_tid(client)
    plan_tid(client, tid)
    confirm_execute(client, tid)
    out = str(tmp_path / "out")
    r = client.post("/api/export", json={"thread_id": tid, "format": "xlsx", "out_dir": out})
    assert r.status_code == 200, r.text
    path = r.json()["path"]
    assert os.path.isfile(path)

    from openpyxl import load_workbook

    wb = load_workbook(path)
    ws = wb.active
    assert ws.title == "清洗结果"
    header = [c.value for c in ws[1]]
    assert header == ["订单号", "客户", "金额", "备注"]
    assert ws.max_row == 4  # 1 表头 + 3 数据行


def test_export_csv_ok_utf8_sig(client, tmp_path):
    tid = parse_tid(client)
    plan_tid(client, tid)
    confirm_execute(client, tid)
    out = str(tmp_path / "out")
    r = client.post("/api/export", json={"thread_id": tid, "format": "csv", "out_dir": out})
    assert r.status_code == 200
    with open(r.json()["path"], encoding="utf-8-sig") as f:
        lines = f.read().strip().splitlines()
    assert lines[0] == "订单号,客户,金额,备注"
    assert len(lines) == 4


def test_export_unsupported_format_400(client, tmp_path):
    tid = parse_tid(client)
    plan_tid(client, tid)
    confirm_execute(client, tid)
    r = client.post("/api/export", json={"thread_id": tid, "format": "xml", "out_dir": str(tmp_path)})
    assert r.status_code in (400, 500), r.text  # 未知格式被拒（400 或 fail-loud 500）
    # 拒绝时不落任何半成品（threads/ 为运行时线程引用目录，审计库为 test-runs.db，均非导出产物）
    runtime_names = ("threads",)
    leftovers = [p for p in tmp_path.glob("*")
                 if p.name not in runtime_names and not p.name.startswith("test-runs.db")]
    assert not leftovers


def test_export_suite_all_formats_with_attachments(client, tmp_path):
    """套件：7 种主格式 + 问题明细/汇总 CSV + 配方 JSON 同批落盘。"""
    tid = parse_tid(client)
    plan_tid(client, tid)
    confirm_execute(client, tid)
    client.post("/api/verify", json={"thread_id": tid})
    client.post("/api/report", json={"thread_id": tid, "format": "md"})
    out = tmp_path / "out"

    for fmt in ("csv", "xlsx", "ods", "pdf", "json", "sql", "template"):
        r = client.post("/api/export", json={"thread_id": tid, "format": fmt, "out_dir": str(out)})
        assert r.status_code == 200, f"{fmt}: {r.text}"
        body = r.json()
        assert os.path.isfile(body["path"])
        assert body["files"][0] == body["path"]
    assert list(out.glob("*issues*.csv")) and list(out.glob("*issues_summary.csv"))
    assert list(out.glob("*_recipe.json"))


# ---------------------------------------------------------------------------
# /api/run/{run_id}
# ---------------------------------------------------------------------------


def test_run_status_ok(client):
    tid = parse_tid(client)
    r = client.get(f"/api/run/{tid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_id"] == tid
    # 节点名与状态键避让后的真实图节点名一致
    assert [n["node_name"] for n in body["nodes"]] == [
        "parse", "eda", "plan", "confirm", "execute", "verify_check", "report_build", "export"]


def test_run_status_not_found_404(client):
    r = client.get("/api/run/clean-no-such")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# /api/recipe-import（配方导入一键重放）
# ---------------------------------------------------------------------------


def test_recipe_import_ok(client):
    recipe = {
        "schema_id": "clean-recipe/v1",
        "name": "demo-recipe",
        "operations": [{"op": "row_dedupe", "params": {"subset": ["订单号"]}}],
    }
    r = client.post("/api/recipe-import", json={"recipe_json": recipe})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["steps"] == 1
    assert body["thread_id"].startswith("clean-")


def test_recipe_import_invalid_400(client):
    r = client.post("/api/recipe-import", json={"recipe_json": {"schema_id": "x", "operations": [
        {"op": "no_such_op", "params": {}}]}})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# /api/clean 与 /api/run（全流程自动化）
# ---------------------------------------------------------------------------


def test_clean_pipeline_auto_confirm(client):
    """auto_confirm 也必须过覆盖校验 —— 未覆盖高危项时自动确认不得越权放行。"""
    r = client.post("/api/clean", json={
        "file_name": "orders.csv", "file_type": "csv", "file_size": len(CSV_SAMPLE),
        "content_b64": b64(CSV_SAMPLE),
        "operations": [{"op": "row_dedupe", "params": {"subset": ["订单号"]}}],
        "auto_confirm": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stage"] == "awaiting_confirm", body
    assert body["code"] == "COVERAGE_BLOCKED"
    assert {u["issue_name"] for u in body["uncovered_high"]} == {"null", "outlier"}
    assert len(body["profile"]["issues"]) == 9


def test_clean_pipeline_auto_confirm_when_covered(client):
    """覆盖齐备（含异常值处理）时 auto_confirm 正常跑完 —— 硬门只拦"未覆盖"，不拦正常路径。"""
    ops = [
        {"op": "row_dedupe", "params": {"subset": ["订单号"]}},
        {"op": "cell_fill_missing", "params": {"column": "备注", "method": "constant", "value": "无"}},
        {"op": "cell_amount_clean", "params": {"column": "金额"}},
        {"op": "row_delete", "params": {"column": "金额", "value": "99999"}},  # 覆盖 outlier（异常值）
    ]
    r = client.post("/api/clean", json={
        "file_name": "orders.csv", "file_type": "csv", "file_size": len(CSV_SAMPLE),
        "content_b64": b64(CSV_SAMPLE), "operations": ops, "auto_confirm": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    # 硬门只拦"未覆盖"：覆盖齐备时自动确认照常放行（本样本 4 行，删行后空值率口径可能触发既有
    # empty_ratio 相对目标 → stage 可为 verify_failed，均属"已放行执行"，与本版硬门无关）
    assert body.get("code") != "COVERAGE_BLOCKED", body
    assert body["stage"] in ("verified", "verify_failed", "executed", "reported"), body
    assert len(body["profile"]["issues"]) == 9


def test_run_pipeline_awaits_confirm(client):
    r = client.post("/api/run", json={
        "file_name": "orders.csv", "file_type": "csv", "file_size": len(CSV_SAMPLE),
        "content_b64": b64(CSV_SAMPLE),
        "operations": [{"op": "row_dedupe", "params": {"subset": ["订单号"]}}],
        "auto_confirm": False,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stage"] == "awaiting_confirm"
    assert "配方待人工确认" in body["message"]


# ---------------------------------------------------------------------------
# /api/parse 的 thread_id 存在性校验（未知 tid → 404，不再是 500）
# ---------------------------------------------------------------------------

CSV_MIXED_UNIT = "订单号,数量\n10001,3件\n10002,5\n10003,2kg\n"


def parse_with_tid(client, tid, content=CSV_SAMPLE, name="orders.csv", ftype="csv"):
    raw = content.encode("utf-8") if isinstance(content, str) else content
    return client.post("/api/parse", json={
        "file_name": name, "file_type": ftype, "file_size": len(raw),
        "file_hash": "", "content_b64": b64(raw), "thread_id": tid,
    })


def test_parse_unknown_thread_id_returns_404_not_500(client):
    """未知 thread_id 由 `_get_entry` 统一裁决 → 404；不得再冒泡 KeyError 成 500。"""
    r = parse_with_tid(client, "clean-不存在-9f3a")
    assert r.status_code == 404, r.text
    assert "不存在" in str(r.json()["detail"])
    assert "Traceback" not in r.text and "KeyError" not in r.text


def test_parse_unknown_thread_id_checked_before_parsing(client):
    """校验点须在 parse_stream **之前**：未知 tid + 非法载荷 → 仍 404（若先解析会先撞 400）。"""
    r = parse_with_tid(client, "clean-不存在-7b21", content=b"irrelevant", ftype="exe")
    assert r.status_code == 404, r.text


def test_parse_existing_thread_id_reuse_unchanged(client):
    """复用路径行为不变：已存在 tid 再次 parse 正常覆盖输入并沿用同一 tid。"""
    tid = parse_tid(client)
    new_csv = "订单号,客户,金额,备注\n20001,赵六,12.5,ok\n"
    r = parse_with_tid(client, tid, content=new_csv, name="orders_v2.csv")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["thread_id"] == tid
    assert body["row_count"] == 1
    # 复用后下游链路照常（未因新增校验被挡）
    assert client.post("/api/eda", json={"thread_id": tid}).status_code == 200


# ---------------------------------------------------------------------------
# 端到端复跑：含非计数单位的混排列（`3件` / `5` / `2kg`）
# ---------------------------------------------------------------------------


def test_mixed_unit_column_strip_keeps_non_count_unit_e2e(client):
    """端到端：`3件`→3、`5`→5、`2kg` **存活**，
    执行日志与报告两侧均如实披露跳过计数（不静默、不编造）。"""
    tid = parse_tid(client, content=CSV_MIXED_UNIT, name="mixed_unit.csv")
    plan_tid(client, tid, ops=[{"op": "cell_unit_convert",
                                "params": {"column": "数量", "from": "件", "to": "纯数值"}}],
             name="strip-mixed-unit")
    body = confirm_execute(client, tid)
    values = [row[1] for row in body["rows"]]
    assert values[0] == 3 and str(values[1]) == "5" and values[2] == "2kg", values
    entry = [e for e in body["transform_log"] if e["op"] == "cell_unit_convert"][0]
    assert entry["skipped_non_count"] == 1
    assert entry["skipped_non_samples"] == ["2kg"]
    # 报告侧同样披露（未处理项不得漏掉"保留原值"的 2kg）
    client.post("/api/verify", json={"thread_id": tid})
    rep = client.post("/api/report", json={"thread_id": tid, "format": "json"}).json()
    unhandled = rep["content"]["sections"]["4_unhandled"]["unhandled"]
    hit = [i for i in unhandled if i["issue_name"] == "cell_unit_convert"]
    assert len(hit) == 1 and hit[0]["affected_rows"] == 1, unhandled
    assert "2kg" in hit[0]["reason"]
