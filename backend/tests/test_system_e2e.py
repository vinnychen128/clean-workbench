# SPDX-License-Identifier: Apache-2.0
"""L3 系统测试：全链路场景（L3 图 / 确定性替代专项）。

覆盖：HTTP 全链路（parse→eda→plan→confirm→execute→verify→report→export→run_status）、
人工门红队（未确认不执行）、无外联（出站=0）、GBK/UTF-8 编码兼容、配方重放逐字节一致、
中断恢复（HITL 门后继续）。
"""
import io


from tests.test_integration_api import confirm_execute, do_parse, parse_tid, plan_tid

FLOW_OPS = [
    {"op": "row_dedupe", "params": {"subset": ["订单号"]}},
    {"op": "cell_fill_missing", "params": {"column": "备注", "method": "constant", "value": "无"}},
    {"op": "cell_amount_clean", "params": {"column": "金额"}},
]


def test_full_http_flow(client, tmp_path):
    """全链路：健康 → 解析 → 体检 → 配方 → 确认 → 执行 → 校验 → 报告 → 导出 → 进度。"""
    assert client.get("/api/health").status_code == 200

    tid = parse_tid(client)
    assert client.post("/api/eda", json={"thread_id": tid}).status_code == 200

    body = plan_tid(client, tid, ops=FLOW_OPS)
    assert body["steps"][0]["op"] == "row_dedupe"
    assert len(body["steps"]) == len(FLOW_OPS)  # 注：dependencies 字段不在本断言范围

    # 后端直调（不带 override）在存在未覆盖高危项时必须被 409 拦住
    blocked = client.post("/api/confirm", json={"thread_id": tid, "approve": True})
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"]["code"] == "COVERAGE_BLOCKED"
    assert blocked.json()["detail"]["uncovered_high"]
    # 带 override.ack + 说明 → 放行并留痕
    ok = client.post("/api/confirm", json={
        "thread_id": tid, "approve": True,
        "override": {"ack": True, "note": "用例说明：已知情跳过未覆盖高危项，继续验证后续链路"},
    })
    assert ok.status_code == 200, ok.text
    assert ok.json()["override"]["ack"] is True
    ex = client.post("/api/execute", json={"thread_id": tid}).json()
    assert ex["transform_log"], "转换日志不得为空"

    vr = client.post("/api/verify", json={"thread_id": tid}).json()
    assert "metrics" in vr

    md = client.post("/api/report", json={"thread_id": tid, "format": "md"}).json()["content"]
    assert "# 清洗报告" in md

    out = str(tmp_path / "out")
    exp = client.post("/api/export", json={"thread_id": tid, "format": "csv", "out_dir": out})
    assert exp.status_code == 200 and exp.json()["path"]

    rs = client.get(f"/api/run/{tid}").json()
    names = [n["node_name"] for n in rs["nodes"]]
    assert names == ["parse", "eda", "plan", "confirm", "execute",
                     "verify_check", "report_build", "export"]
    assert all(n["status"] in ("COMPLETED", "RUNNING", "PENDING") for n in rs["nodes"])


def test_redteam_no_execute_without_confirm(client, tmp_path):
    """红队：配方已生成但未确认 → 不产生任何清洗副本。"""
    tid = parse_tid(client)
    plan_tid(client, tid, ops=FLOW_OPS)

    r = client.post("/api/execute", json={"thread_id": tid})
    assert r.status_code == 409

    r = client.post("/api/export", json={"thread_id": tid, "format": "xlsx", "out_dir": str(tmp_path)})
    assert r.status_code == 400

    rs = client.get(f"/api/run/{tid}").json()
    assert rs["stage"] == "awaiting_confirm"
    assert not list(tmp_path.rglob("*.xlsx")), "未确认时不得落盘清洗副本"


def test_offline_no_outbound_requests(client, monkeypatch):
    """无外联：拦截所有真实出站 socket，全流程仍可跑通。"""
    import socket

    real_connect = socket.socket.connect

    def guarded_connect(self, address, *a, **kw):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in ("127.0.0.1", "localhost"):
            raise AssertionError(f"检测到出站连接: {address}")
        return real_connect(self, address, *a, **kw)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)

    tid = parse_tid(client)
    client.post("/api/eda", json={"thread_id": tid})
    plan_tid(client, tid, ops=FLOW_OPS)
    client.post("/api/confirm", json={"thread_id": tid, "approve": True})
    client.post("/api/execute", json={"thread_id": tid})
    client.post("/api/verify", json={"thread_id": tid})
    r = client.post("/api/report", json={"thread_id": tid, "format": "md"})
    assert r.status_code == 200


def test_gbk_and_utf8_encoding_compatible(client):
    """编码兼容：GBK / UTF-8 中文列名与内容均正常。"""
    gbk_raw = "订单号,客户,金额\n10001,张三,88\n10002,李四,99\n".encode("gbk")
    utf8_raw = "订单号,客户,金额\n10001,张三,88\n10002,李四,99\n".encode("utf-8")

    for raw in (gbk_raw, utf8_raw):
        tid = parse_tid(client, content=raw)
        rs = client.get(f"/api/run/{tid}").json()
        assert rs["stage"] == "parsed"
        # 列信息已在 parse 返回中验证（L2）；此处验证流程可继续
        assert client.post("/api/eda", json={"thread_id": tid}).status_code == 200


def test_replay_recipe_byte_identical(client, tmp_path):
    """可复现：同文件同配方重放 → 导出结果逐字节一致。"""
    outputs = []
    for _ in range(2):
        tid = parse_tid(client)
        plan_tid(client, tid, ops=FLOW_OPS)
        confirm_execute(client, tid)
        out = str(tmp_path / f"out_{_}")
        exp = client.post("/api/export", json={"thread_id": tid, "format": "csv", "out_dir": out}).json()
        with open(exp["path"], encoding="utf-8-sig") as f:
            outputs.append(f.read())
    assert outputs[0] == outputs[1], "同配方重放结果必须逐字节一致"


def test_interrupt_resume_after_hitl(client):
    """中断恢复：HITL 门中断后确认即可继续，不丢失状态。"""
    tid = parse_tid(client)
    plan_tid(client, tid, ops=FLOW_OPS)
    # HITL 门：配方生成后即进入待确认（实现 stage 语义为 "plan"，规格枚举兼容 "awaiting_confirm"）
    assert client.get(f"/api/run/{tid}").json()["stage"] in ("plan", "awaiting_confirm")

    # “重启”模拟：新客户端实例不可行（状态在内存），改用同一客户端继续 —— 等价于恢复会话
    # 带越权确认（如实填说明）放行，验证后续中断恢复链路不受硬门影响
    client.post("/api/confirm", json={
        "thread_id": tid, "approve": True,
        "override": {"ack": True, "note": "中断恢复用例：已知情跳过未覆盖高危项"},
    })
    r = client.post("/api/execute", json={"thread_id": tid})
    assert r.status_code == 200
    assert r.json()["transform_log"][0]["op"] == "row_dedupe"


def test_scanned_pdf_rejected_or_clear_message(client):
    """扫描版 PDF：不产出假数据（pypdf 写无文本层空白页 = 等价扫描件；拒收并明确提示）。"""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)  # 空白页 = 无文本层，等价扫描件
    buf = io.BytesIO()
    writer.write(buf)
    r = do_parse(client, content=buf.getvalue(), name="scan.pdf", ftype="pdf")
    assert r.status_code == 400
    assert "扫描件" in r.json()["detail"] or "不支持" in r.json()["detail"]


# 触发多类体检问题（金额中文后缀 / 非标准日期 / 单位混用 / 重复 / 空值 / 异常值）
AUTO_RUN_CSV = ("订单号,客户,金额,备注,数量,日期\n"
                "10001,张三,100.5元,ok,3件,2024/5/6\n"
                "10001,张三,100.5元,ok,3件,2024/5/6\n"
                "10002,李四,,缺金额,5,2024.05.06\n"
                "10003,王五,99999,异常,2kg,20240808\n")


def test_auto_confirm_blocked_then_override_traced_in_report(client, tmp_path):
    """图编排路径（/api/run 自动确认）被硬门拦下后带 override 放行，报告必须留痕。

    回归点：图内 state 是副本，越权记录写在服务层 state 上，若不同步回填，
    图内构建的报告会丢「经用户确认未处理」标注与 `3_quality.overrides`。
    """
    from tests.test_integration_api import b64

    raw = AUTO_RUN_CSV.encode("utf-8")
    r = client.post("/api/run", json={
        "file_name": "auto.csv", "file_type": "csv", "file_size": len(raw),
        "content_b64": b64(raw), "operations": FLOW_OPS, "auto_confirm": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == "COVERAGE_BLOCKED" and body["stage"] == "awaiting_confirm", body
    tid = body["thread_id"]
    assert body["uncovered_high"], "本用例数据必须存在未覆盖高危项"

    ok = client.post("/api/confirm", json={
        "thread_id": tid, "approve": True,
        "override": {"ack": True, "skipped": [body["uncovered_high"][0]["issue_name"]],
                     "note": "用例说明：已知情跳过未覆盖高危项，继续验证留痕"}})
    assert ok.status_code == 200, ok.text
    assert ok.json()["override"]["ack"] is True

    rep = client.post("/api/report", json={"thread_id": tid, "format": "json"}).json()["content"]
    assert rep["sections"]["3_quality"].get("overrides"), "越权放行必须在报告 3_quality.overrides 留痕"
    acked = [u for u in rep.get("unhandled", []) if u.get("user_acknowledged")]
    assert acked, "被跳过的未处理项必须标 user_acknowledged"
    assert "经用户确认未处理" in acked[0]["reason"], acked[0]
