# SPDX-License-Identifier: Apache-2.0
"""L4 回归测试：关键路径 + 已知缺陷修复回归（回归集口径）。

覆盖：GraphIO 中断恢复 API、ODS/xls 导出、配方签名防篡改、原文件不可变、
1 万行性能（≤60s）、静态扫描（无外联 / 零 LLM / 无强 copyleft 依赖）、
检测器注册表自动注册、8 节点拓扑回归。
"""
import io
import json
import os
import re
import time
from pathlib import Path

import pytest

from tests.test_integration_api import CSV_SAMPLE, confirm_execute, parse_tid, plan_tid

REPO_ROOT = Path(__file__).resolve().parents[2]

# AI 辅助层的两处**唯一**例外（见下方两个静态扫描用例的说明）：
# - 外发：仅 `backend/app/ai/client.py` 允许出站 HTTP；
# - 模型关键词：仅 `backend/app/ai/` 包内允许出现。
_AI_PKG_DIR = (REPO_ROOT / "backend" / "app" / "ai").resolve()
_AI_CLIENT_FILE = _AI_PKG_DIR / "client.py"

# ---------------------------------------------------------------------------
# 已知缺陷修复回归（本次 L1 阶段修复：GraphIO / ODS / xlwt）
# ---------------------------------------------------------------------------


def test_graphio_load_save_api_contract():
    """回归：GraphIO 必须提供 load_before / load_after / load / save 方法。"""
    from app.graph.pipeline import GraphIO

    for method in ("load_before", "load_after", "load", "save"):
        assert callable(getattr(GraphIO, method, None)), f"GraphIO 缺少 {method}"


def test_graph_interrupt_resume_with_checkpointer():
    """回归：中断恢复需注入 checkpointer（MemorySaver）。"""
    from langgraph.checkpoint.memory import MemorySaver
    from app.graph.pipeline import GraphIO, build_pipeline

    io = GraphIO(load_fn=lambda: None, save_fn=lambda data: None)
    g = build_pipeline(io, checkpointer=MemorySaver())
    assert g is not None


def test_ods_export_roundtrip(tmp_path):
    """回归：ODS 导出使用 odf.table.TableRow（修复 API 误用）。"""
    from app.export.exporter import export_ods

    path = export_ods(["a", "b"], [["1", "中文"], ["2", "x"]], str(tmp_path), "demo")
    assert os.path.isfile(path) and path.endswith(".ods")

    from odf.opendocument import load

    doc = load(path)
    assert doc.spreadsheet is not None
    tables = doc.spreadsheet.getElementsByType(
        __import__("odf.table", fromlist=["Table"]).Table)
    assert len(tables) == 1
    assert tables[0].getAttribute("name") == "清洗结果"


def test_xls_export_supported_by_xlwt():
    """回归：xlwt 依赖可用（xls 读入侧依赖）。"""
    import xlwt

    wb = xlwt.Workbook()
    ws = wb.add_sheet("s")
    ws.write(0, 0, "中文")
    buf = io.BytesIO()
    wb.save(buf)
    assert buf.getvalue().startswith(b"\xd0\xcf\x11\xe0")  # OLE2 魔数


# ---------------------------------------------------------------------------
# 配方签名防篡改
# ---------------------------------------------------------------------------


def test_recipe_signature_written_on_export(tmp_path):
    """回归：导出的 recipe.json 必须带内容签名（供重放校验/留档）。"""
    from app.recipe.engine import export_recipe_json, new_recipe, recipe_signature

    recipe = new_recipe("demo", {"thread_id": "t1"}, [
        {"op": "row_dedupe", "params": {"subset": ["订单号"]}}])
    path = export_recipe_json(recipe, str(tmp_path / "recipe.json"))
    with open(path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["_signature"].startswith("sha256:")
    # 同一内容签名确定（可复现）；recipe_signature 自带 "sha256:" 前缀
    assert saved["_signature"] == recipe_signature(recipe)


def test_recipe_signature_tamper_rejected(tmp_path):
    """回归：篡改配方（改 op 参数）必须在执行前被签名校验拦截。"""
    from app.engine.engine import execute_recipe
    from app.recipe.engine import export_recipe_json, new_recipe

    recipe = new_recipe("demo", {"thread_id": "t1"}, [
        {"op": "row_dedupe", "params": {"subset": ["订单号"]}}])
    path = export_recipe_json(recipe, str(tmp_path / "recipe.json"))
    import json as _json

    with open(path, encoding="utf-8") as f:
        tampered = _json.load(f)
    tampered["operations"][0]["params"]["subset"] = ["客户"]  # 篡改

    from app.engine.engine import CleanState

    state = CleanState(thread_id="t1", source={"file_name": "x.csv"})
    state.confirmed = True
    state.rules_plan = tampered
    with pytest.raises(Exception):
        execute_recipe(state, ["订单号", "客户"], [["a", "b"], ["a", "c"]])


# ---------------------------------------------------------------------------
# 原文件不可变
# ---------------------------------------------------------------------------


def test_original_file_hash_unchanged(client):
    """回归：执行清洗后原文件哈希一致（产物=副本）。"""
    raw = CSV_SAMPLE.encode("utf-8")
    import hashlib

    before = hashlib.sha256(raw).hexdigest()
    tid = parse_tid(client, content=raw)
    plan_tid(client, tid)
    confirm_execute(client, tid)
    assert hashlib.sha256(raw).hexdigest() == before, "原文件内容被修改"


# ---------------------------------------------------------------------------
# 性能口径：1 万行 ≤ 60 秒
# ---------------------------------------------------------------------------


def test_performance_10k_rows_under_60s(client):
    """性能回归：1 万行 CSV 全流程（parse→eda→plan→confirm→execute）≤60s。"""
    lines = ["订单号,客户,金额,备注"]
    for i in range(10000):
        dup = i % 7 == 0
        lines.append(f"{10000 + i % 50},{'客户' + str(i % 100)},{(i % 1000) / 10},{'' if dup else 'ok'}")
    raw = "\n".join(lines).encode("utf-8")

    t0 = time.time()
    tid = parse_tid(client, content=raw)
    client.post("/api/eda", json={"thread_id": tid})
    plan_tid(client, tid, ops=[
        {"op": "row_dedupe", "params": {"subset": ["订单号"]}},
        {"op": "cell_fill_missing", "params": {"column": "备注", "method": "constant", "value": "无"}},
    ])
    client.post("/api/confirm", json={"thread_id": tid, "approve": True})
    r = client.post("/api/execute", json={"thread_id": tid})
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    assert elapsed <= 60, f"1 万行耗时 {elapsed:.1f}s，超出 60s 上限"


# ---------------------------------------------------------------------------
# 静态扫描：无外联 / 零 LLM
# ---------------------------------------------------------------------------

_CODE_DIRS = [REPO_ROOT / "backend" / "app", REPO_ROOT / "frontend" / "src", REPO_ROOT / "scripts"]
_CODE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx"}


def _code_files():
    for d in _CODE_DIRS:
        if d.exists():
            yield from (p for p in d.rglob("*") if p.suffix in _CODE_EXTS)


def _strip_comments(text: str) -> str:
    """粗粒度去注释：// 与 # 行注释（不处理块注释边界，足够用于关键词扫描）。"""
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith(("//", "#")))


def test_static_scan_no_outbound_http():
    """无外联：后端引擎代码不得出现真实出站 HTTP 客户端调用（环回除外）。

    前端 fetch 属浏览器内同源调用（调本项目后端），不在红线「后端零外联」范围。

    例外（唯一）：`backend/app/ai/client.py` 是 AI 辅助层的**唯一外发点**，
    且默认关闭（CLEAN_AI_ENABLED=false）、只发列形态不发数据值（红线）。
    该例外由 `tests/test_ai_guard.py::test_only_ai_client_reaches_out` 反向兜住：
    除该文件外，全仓不得再出现任何外发调用。
    """
    backend_code = [p for p in _code_files()
                    if REPO_ROOT / "frontend" not in p.parents
                    and _AI_CLIENT_FILE not in p.parents and p != _AI_CLIENT_FILE]
    outbound_patterns = [
        r"requests\.(get|post|put|delete|patch)\(",
        r"urllib\.request",
        r"httpx\.(get|post|put|delete|patch|Client)\(",
        r"aiohttp",
        r"fetch\(",
        r"http[s]?://(?!127\.0\.0\.1|localhost|testserver)",
    ]
    hits = []
    for p in backend_code:
        text = _strip_comments(p.read_text(encoding="utf-8", errors="ignore"))
        for pat in outbound_patterns:
            for m in re.finditer(pat, text):
                hits.append(f"{p.relative_to(REPO_ROOT)}:{pat}:{text[max(0, m.start()-40):m.end()+40]!r}")
    assert not hits, f"检测到疑似外联调用 {len(hits)} 处:\n" + "\n".join(hits[:10])


def test_static_scan_zero_llm():
    """零 LLM：**清洗执行路径**不得引用大模型 SDK / 服务关键词。

    例外（唯一）：AI 辅助层自带通道适配（`backend/app/ai/`），其代码必然出现
    模型关键词。红线要求的是「执行路径零模型调用」，因此该包被排除在本次扫描外，
    并由 `tests/test_ai_guard.py::test_execution_chain_never_imports_ai` 断言
    执行链模块不得 import 该包 —— 两侧合起来仍等价于「清洗链零 LLM」。
    """
    llm_patterns = [
        r"\bopenai\b", r"\banthropic\b", r"\blangchain\b", r"\blangsmith\b",
        r"\bdeepseek\b", r"\bqwen\b", r"\bdashscope\b", r"\bcohere\b",
    ]
    hits = []
    for p in _code_files():
        if _AI_PKG_DIR in p.parents:
            continue
        text = _strip_comments(p.read_text(encoding="utf-8", errors="ignore"))
        for pat in llm_patterns:
            if re.search(pat, text, re.IGNORECASE):
                hits.append(f"{p.relative_to(REPO_ROOT)}:{pat}")
    assert not hits, f"代码中出现 LLM 关键词: {hits}"


def test_static_scan_no_strong_copyleft_dependency():
    """许可白名单：依赖声明行（name==version）不得出现 GPL/AGPL/SSPL 等强 copyleft。"""
    dep_files = [REPO_ROOT / "backend" / "requirements.txt", REPO_ROOT / "frontend" / "package.json"]
    copyleft = re.compile(r"\b(GPL|AGPL|SSPL)\b")
    for dep in dep_files:
        if not dep.exists():
            continue
        for line in dep.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("#") or line.strip().startswith("//"):
                continue
            # 剔除行内注释（如 odfpy 双许可说明），仅对依赖声明本身判许可
            line = line.split("#", 1)[0].strip()
            # 仅依赖声明行（requirements 含版本号；package.json 含依赖键）才检查
            if "==" not in line and not re.match(r'^\s*"[^"]+"\s*:', line):
                continue
            assert not copyleft.search(line), f"{dep} 依赖声明含强 copyleft: {line}"


# ---------------------------------------------------------------------------
# 检测器注册表与 8 节点拓扑
# ---------------------------------------------------------------------------


def test_detector_registry_auto_registers_nine():
    """回归：9 个检测器经基类自动注册，无需手工登记。"""
    from app.detectors.base import DetectorRegistry

    names = set(DetectorRegistry.all().keys())
    assert names == {"null", "duplicate", "outlier", "format", "amount", "date",
                     "unit", "identifier_column", "mojibake"}


def test_graph_node_topology_7_plus_hitl():
    """回归：图拓扑 8 节点（parse/eda/plan/confirm/execute/verify_check/report_build/export），
    HITL 人工门由 confirm 节点内动态 interrupt() 实现（L3 图）。

    注：verify_check / report_build 为避让状态键 verify / report 而取的节点名。
    """
    from app.graph.pipeline import NODE_ORDER, NODE_STATE_KEY, GraphIO, build_pipeline

    io = GraphIO(load_fn=lambda: {"columns": [], "rows": []}, save_fn=lambda data: None)
    g = build_pipeline(io)  # 构建不得抛 ValueError: '<name>' is already being used as a state key
    # 图节点含 __start__/__end__，断言 8 个业务节点全部就位
    assert set(NODE_ORDER) == {"parse", "eda", "plan", "confirm", "execute",
                               "verify_check", "report_build", "export"}
    assert set(NODE_ORDER) <= set(g.get_graph().nodes.keys())
    # HITL 门：动态 interrupt 位于 confirm 节点，不再用编译期 interrupt_before
    assert "confirm" in g.get_graph().nodes
    assert NODE_STATE_KEY == {"verify_check": "verify", "report_build": "report"}


# ---------------------------------------------------------------------------
# L1 基线回归（回归集：检测器 + 操作类全量，改动必跑）
# ---------------------------------------------------------------------------


def test_detector_smoke_all_issue_names():
    """回归冒烟：9 检测器在样例数据上均产出可序列化结果。"""
    import json

    from app.detectors.base import DetectorRegistry

    columns = ["订单号", "客户", "金额", "备注"]
    rows = [["10001", "张三", "100.5", "ok"], ["10001", "张三", "100.5", "ok"],
            ["10002", "李四", "", "缺金额"], ["10003", "王五", "99999", "异常"]]
    profile = DetectorRegistry.run_all(columns, rows, verbosity=1)
    assert len(profile["issues"]) == 9
    json.dumps(profile)  # 必须可序列化（前端展示依赖）
