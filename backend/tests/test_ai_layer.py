# SPDX-License-Identifier: Apache-2.0
"""AI 辅助层测试。

覆盖验收条目：
  provider 切换只改配置不改代码
  默认 value_sharing=shape_only；请求体不含任何原始值
  相同输入第二次调用命中缓存（cached=true）
  台账字段齐备且不含数据值
  端点不可达时 /api/ai/status 返回 200 + reachable=false，其余功能零影响
  语义类型 ∈ 受控枚举 + 依据 + 建议算子 ∈ 既有算子目录
  坏结构 → 重试 1 次 → degraded=true，不产生任何数据改动
  人点「加入配方」→ 标准配方步骤（与既有契约同构、可重放）
  反例：AI 建议未经人确认 ⇒ 配方零变化
  未点开不调用（台账无记录）
  人话摘要只读：导出默认不含该文本
  disclaimer 字段非空
  缓存命中行为正确
  「会发送什么」预览与实际请求体一致
  端点不接收密钥字段（收到即 400）

说明：本文件不发起任何真实网络请求 —— 通过替换 `AiClient.complete` 注入可控模型输出，
      缓存 / 台账走真实实现（重定向到 tmp_path），故验的是真逻辑。
"""
import json
import re

import pytest

CSV_SAMPLE = (
    "订单号,客户,金额,备注\n"
    "10001,张三,￥1,200.50,ok-DISTINCT\n"
    "10002,李四,￥300.00,ok-DISTINCT\n"
    "10003,王五,,缺失\n"
)
# 用于断言「请求体 / 台账不含原始值」的特征串（不会与列名重合）
RAW_MARKERS = ["￥1,200.50", "￥300.00", "ok-DISTINCT", "10003"]
# 该列名命中敏感词表 → 外发时必须替换为「列#n」
SENSITIVE_COL = "客户"
# 全量 AI 环境变量表：用例必须在「干净环境」下断言默认关行为（见 no_ai_env 夹具）
AI_ENV_KEYS = (
    "CLEAN_AI_ENABLED", "CLEAN_AI_PROVIDER", "CLEAN_AI_BASE_URL", "CLEAN_AI_MODEL",
    "CLEAN_AI_API_KEY", "CLEAN_AI_TIMEOUT_S", "CLEAN_AI_MAX_SAMPLE",
    "CLEAN_AI_VALUE_SHARING", "CLEAN_AI_COLUMN_NAME_SHARING", "CLEAN_AI_CACHE",
)

CANNED_ADVICE = {
    "advice": [
        {
            "column": "金额",
            "semantic_type": "金额",
            "evidence": ["CURRENCY_PREFIX 62%", "NUM+OTHER_UNIT 31%"],
            "suggested_ops": [{"op": "cell_amount_clean", "params": {}}],
            "rationale": "该列多数值带货币符号，建议剥离后按数值处理。",
            "confidence": 0.72,
        }
    ]
}
CANNED_EXPLAIN = {
    "summary": "本次清洗共处理 3 行数据。",
    "bullets": ["金额列存在货币符号。", "备注列存在缺失值。"],
    "next_actions": ["1. 检查金额列。", "2. 补齐备注列。", "3. 复核订单号唯一性。"],
}


# ---------------------------------------------------------------------------
# 通用夹具与辅助
# ---------------------------------------------------------------------------


def b64(text: str) -> str:
    import base64
    return base64.b64encode(text.encode("utf-8")).decode()


@pytest.fixture()
def no_ai_env(monkeypatch):
    """清空**全部** CLEAN_AI_* 环境变量，让用例在「不配 AI」的干净环境里跑。

    必要性：AiConfig 每次构造都读进程环境快照，任何残留的 CLEAN_AI_*（如开发机
    `.env`、CI 变量、别的用例/脚本设置过）都会让「默认关」类断言假失败。
    """
    for key in AI_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return None


@pytest.fixture()
def ai_env(no_ai_env, monkeypatch, tmp_path):
    """把 AI 配置指向一个「假端点」，并把缓存 / 台账重定向到 tmp_path。

    返回 (captured, canned) —— captured 收集真实发出的 messages；canned 决定本轮模型输出。
    """
    from app.ai import client as ai_client

    captured = {"messages": [], "calls": 0, "payloads": []}
    canned = {"value": CANNED_ADVICE}

    monkeypatch.setenv("CLEAN_AI_ENABLED", "true")
    monkeypatch.setenv("CLEAN_AI_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CLEAN_AI_BASE_URL", "http://127.0.0.1:65533/v1")
    monkeypatch.setenv("CLEAN_AI_MODEL", "fake-model")
    monkeypatch.setenv("CLEAN_AI_CACHE", "true")

    monkeypatch.setattr(ai_client, "_cache_dir", lambda: tmp_path / "ai-cache")

    def _as_text(value):
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

    def fake_complete(self, messages, purpose, use_cache=True):
        """复刻真实 complete 的缓存 / 台账语义，只把 HTTP 那一跳换成固定文本。"""
        captured["calls"] += 1
        captured["messages"].append(messages)
        if purpose == "column_advice":
            text = _as_text(canned["value"])
        else:
            text = _as_text(canned.get("explain", CANNED_EXPLAIN))
        key = self.cache_key(messages, purpose)
        if use_cache:
            hit = self.cache_read(key)
            if hit is not None:
                return {"text": hit, "cached": True, "latency_ms": 0, "bytes_sent": 0,
                        "cache_key": key,
                        "ledger": self.ledger_entry(key=key, purpose=purpose, cached=True,
                                                    schema_ok=True)}
        if use_cache:
            self.cache_write(key, text)
        payload = json.dumps(messages, ensure_ascii=False).encode("utf-8")
        captured["payloads"].append(payload)
        return {"text": text, "cached": False, "latency_ms": 1, "bytes_sent": len(payload),
                "cache_key": key,
                "ledger": self.ledger_entry(key=key, purpose=purpose, bytes_sent=len(payload),
                                            cached=False, schema_ok=True)}

    monkeypatch.setattr(ai_client.AiClient, "complete", fake_complete)
    # 探活缓存是模块级全局，逐用例重置，避免用例间串味
    import app.ai.service as ai_service
    monkeypatch.setattr(ai_service, "_PROBE_CACHE",
                        {"at": 0.0, "reachable": False, "last_error": None, "probed": False})
    return captured, canned, tmp_path


def parse_tid(client, content=CSV_SAMPLE, name="ai-orders.csv"):
    resp = client.post("/api/parse", json={
        "file_name": name, "file_type": "csv", "file_size": len(content.encode("utf-8")),
        "file_hash": "", "content_b64": b64(content),
    })
    assert resp.status_code == 200, resp.text
    return resp.json()["thread_id"]


def confirm_execute_only(client, tid):
    """只做「确认 + 执行」（不再重新规划），用于验证 AI 追加的配方本身可跑通。"""
    resp = client.post("/api/confirm", json={"thread_id": tid, "approve": True, "reason": "pytest"})
    if resp.status_code == 409:
        resp = client.post("/api/confirm", json={
            "thread_id": tid, "approve": True, "reason": "pytest",
            "override": {"ack": True, "note": "用例说明：AI 层用例非覆盖校验本身"},
        })
    assert resp.status_code == 200, resp.text
    resp = client.post("/api/execute", json={"thread_id": tid})
    assert resp.status_code == 200, resp.text
    return resp.json()


def run_clean(client, tid, ops=None, name="ai-plan"):
    ops = ops if ops is not None else [{"op": "row_dedupe", "params": {"subset": ["订单号"]}}]
    resp = client.post("/api/plan", json={"thread_id": tid, "operations": ops, "recipe_name": name})
    assert resp.status_code == 200, resp.text
    return confirm_execute_only(client, tid)


def export_to(client, tid, tmp_path, fmt="csv"):
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    resp = client.post("/api/export", json={"thread_id": tid, "format": fmt,
                                            "out_dir": str(out_dir)})
    assert resp.status_code == 200, resp.text
    return resp.json()["path"]


def stage_of(client, tid):
    resp = client.get(f"/api/run/{tid}")
    assert resp.status_code == 200, resp.text
    return resp.json()["stage"]


def ledger_lines(tmp_path):
    path = tmp_path / "ai-cache" / "ai_ledger.jsonl"
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# AI 包纯函数层
# ---------------------------------------------------------------------------


def test_prompt_version_pinned():
    """前置：提示词版本号存在且被缓存键/台账引用（改措辞必须升版本）。"""
    from app.ai.prompts import PROMPT_VERSION
    assert PROMPT_VERSION == "ai-p1"


def test_config_defaults_off(monkeypatch, tmp_path):
    """不配置 = 全关；且默认 value_sharing=shape_only。"""
    from app.ai.config import AiConfig
    monkeypatch.delenv("CLEAN_AI_ENABLED", raising=False)
    cfg = AiConfig(env={})
    assert cfg.enabled is False
    assert cfg.provider == "none"
    assert cfg.value_sharing == "shape_only"
    assert cfg.column_name_sharing == "on"
    assert cfg.validate() == []


def test_config_provider_switch_needs_no_code_change(monkeypatch):
    """本地端点 / 云 API 只改配置，同一套代码路径。"""
    from app.ai.config import AiConfig
    local = AiConfig(env={"CLEAN_AI_ENABLED": "true", "CLEAN_AI_PROVIDER": "openai_compatible",
                          "CLEAN_AI_BASE_URL": "http://127.0.0.1:11434/v1",
                          "CLEAN_AI_MODEL": "qwen2.5:14b"})
    cloud = AiConfig(env={"CLEAN_AI_ENABLED": "true", "CLEAN_AI_PROVIDER": "openai_compatible",
                          "CLEAN_AI_BASE_URL": "https://api.example.com/v1",
                          "CLEAN_AI_MODEL": "cloud-model",
                          "CLEAN_AI_API_KEY": "sk-NOT-A-REAL-KEY"})
    assert local.validate() == [] and cloud.validate() == []
    assert local.key_configured is False and cloud.key_configured is True
    # 密钥绝不回显在任何对外视图里
    assert "sk-NOT-A-REAL-KEY" not in json.dumps(cloud.public_view(), ensure_ascii=False)


def test_config_invalid_values_reported():
    """配置非法值如实上报（不静默吞掉）。"""
    from app.ai.config import AiConfig
    bad = AiConfig(env={"CLEAN_AI_ENABLED": "true", "CLEAN_AI_PROVIDER": "openai_compatible",
                        "CLEAN_AI_VALUE_SHARING": "raw_values"})
    assert any("VALUE_SHARING" in e for e in bad.validate())


def test_sensitive_column_masking():
    """敏感列名词表：命中即 masked 为 列#n（fail-closed）。"""
    from app.ai.config import AiConfig, is_sensitive_column
    assert is_sensitive_column("客户") is True
    assert is_sensitive_column("身份证号") is True
    assert is_sensitive_column("") is True
    assert is_sensitive_column("金额") is False
    on = AiConfig(env={})
    assert on.column_label("客户", 1) == "列#1"
    assert on.column_label("金额", 2) == "金额"
    masked = AiConfig(env={"CLEAN_AI_COLUMN_NAME_SHARING": "masked"})
    assert masked.column_label("金额", 2) == "列#2"


def test_sensitive_wordlist_exact_24():
    """精确词表（24 词）：逐词命中；普通列名不误伤。"""
    from app.ai.config import SENSITIVE_WORDS, is_sensitive_column
    assert len(SENSITIVE_WORDS) == 24, f"精确词表应为 24 词，实际 {len(SENSITIVE_WORDS)}"
    for word in SENSITIVE_WORDS:
        assert is_sensitive_column(word), f"词表词未命中：{word}"
    for ok in ("金额", "数量", "成交日期", "备注", "重量", "单价"):
        assert not is_sensitive_column(ok), f"普通列名被误判为敏感：{ok}"


def test_sensitive_suffix_heuristic_and_fail_closed():
    """后缀启发式（名/号/电话/地址/账号/邮箱/证件）+ 归属词兜底（fail-closed）。"""
    from app.ai.config import is_sensitive_column
    for name in ("收货地址", "会员号", "备用电话", "结算账号", "工作邮箱", "军官证件",
                 "客户等级", "个人备注", "员工编号", "用户偏好"):
        assert is_sensitive_column(name), f"后缀/归属词未命中：{name}"
    # 大小写不敏感（中英同表）+ 空白容错
    assert is_sensitive_column("  EMAIL  ") is True
    assert is_sensitive_column("E-mail") is True
    assert is_sensitive_column(None) is True


def test_sensitive_columns_never_leave_machine(client, ai_env):
    """（端到端）：敏感列名不得原样外发，一律换为「列#n」身份串。

    注意区分「列名身份」与「提示词里的受控语义类型枚举」：后者是代码内置静态文本
    （如语义类型 `邮箱` 一词必然出现在系统提示词里），与客户数据无关，不算泄漏。
    """
    from app.ai.config import SEMANTIC_TYPES, is_sensitive_column
    csv = (
        "订单号,客户姓名,手机号,邮箱,金额,备注\n"
        "A1001,张三,13812345678,zhang@example.com,￥88.00,ok-1\n"
        "A1002,李四,13900000000,li@example.com,￥99.50,ok-2\n"
    )
    captured, _canned, _tmp = ai_env
    tid = parse_tid(client, content=csv, name="ai-sensitive.csv")
    assert client.post("/api/ai/column-advice", json={"thread_id": tid}).status_code == 200
    body = json.dumps(captured["messages"][0], ensure_ascii=False)

    all_columns = ["订单号", "客户姓名", "手机号", "邮箱", "金额", "备注"]
    sensitive = [c for c in all_columns if is_sensitive_column(c)]
    assert sensitive == ["订单号", "客户姓名", "手机号", "邮箱"], sensitive

    identities = set(re.findall(r"列「([^」]*)」", body))
    leaked = sorted(set(sensitive) & identities)
    assert not leaked, f"敏感列名原样外发：{leaked}；实际出站列名身份={sorted(identities)}"
    # 非枚举同形的敏感列名连「文本出现」都不允许
    hard = [c for c in sensitive if c not in SEMANTIC_TYPES]
    assert not [c for c in hard if c in body], f"敏感列名出现在外发文本中：{hard}"
    # 敏感列确实被 mask（每个都对应一个 列#n 身份）
    masked = {i for i in identities if i.startswith("列#")}
    assert len(masked) >= len(sensitive), f"mask 数量不足：{sorted(masked)}"
    # 非敏感列名保持原样（不误伤）
    assert {c for c in ("金额", "备注")} <= identities


def test_redact_samples_rules():
    """脱敏规则（仅第二档）：手机 / 邮箱 / 身份证 / 长数字 / 姓名 / 地址 / 卡号。"""
    from app.ai.redact import redact_samples
    out = redact_samples(["13812345678", "a@b.com", "张三", "6222021234567890123", "12.5"])
    joined = " | ".join(str(o) for o in out)
    assert "13812345678" not in joined
    assert "a@b.com" not in joined
    assert "张三" not in joined
    assert "6222021234567890123" not in joined


# ---------------------------------------------------------------------------
# 端点层
# ---------------------------------------------------------------------------


def test_ac19_1_status_when_disabled_never_500(client, no_ai_env):
    """未启用时 /api/ai/status 正常应答且如实标 disabled，既有端点不受影响。"""
    r = client.get("/api/ai/status", params={"tid": "t_x"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["enabled"] is False
    assert body["provider"] == "none"
    assert body["value_sharing"] == "shape_only"
    assert body["key_configured"] is False
    assert body["reachable"] is False
    assert body["last_error"] == "disabled"
    assert "api_key" not in json.dumps(body, ensure_ascii=False)
    # 既有端点零影响
    assert client.get("/api/health").status_code == 200


def test_ac19_6_unreachable_status_200_reachable_false(client, monkeypatch, no_ai_env, tmp_path):
    """端点不可达 → 200 + reachable=false，其余功能零影响。"""
    from app.ai import client as ai_client
    import app.ai.service as ai_service
    monkeypatch.setenv("CLEAN_AI_ENABLED", "true")
    monkeypatch.setenv("CLEAN_AI_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CLEAN_AI_BASE_URL", "http://127.0.0.1:65534/v1")  # 无监听端口
    monkeypatch.setenv("CLEAN_AI_MODEL", "fake-model")
    monkeypatch.setattr(ai_client, "_cache_dir", lambda: tmp_path / "ai-cache")
    monkeypatch.setattr(ai_service, "_PROBE_CACHE",
                        {"at": 0.0, "reachable": False, "last_error": None, "probed": False})

    r = client.get("/api/ai/status", params={"tid": "t_x", "probe": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reachable"] is False
    assert body["last_error"]
    assert body["enabled"] is True
    assert client.get("/api/health").status_code == 200


def test_ac19_3_request_body_has_no_raw_values(client, ai_env):
    """默认只发形态标签与列级统计，请求体不含任何原始值。"""
    captured, _canned, _tmp = ai_env
    tid = parse_tid(client)
    r = client.post("/api/ai/column-advice", json={"thread_id": tid})
    assert r.status_code == 200, r.text
    assert captured["messages"], "必须真实构造过一次请求"
    blob = json.dumps(captured["messages"], ensure_ascii=False)
    for marker in RAW_MARKERS:
        assert marker not in blob, f"请求体泄露原始值：{marker}"
    # 列名命中敏感词 → 已替换为 列#n（原列名不得外发）
    assert SENSITIVE_COL not in blob
    assert "列#" in blob


def test_ac23_3_preview_matches_actual_request(client, ai_env):
    """设置页「会发送什么」预览与实际请求体一致。"""
    from app.ai.service import AiService
    preview = AiService().sent_preview()
    # 预览字段 ↔ 实际消息中的表达，一一对应（映射即口径）
    marker_map = {
        "column_name": ["列「"],
        "cell_profile": ["形态分布"],
        "cell_counts": ["非空率", "唯一值"],
        "length_stats": ["长度"],
    }
    for field in preview["fields"]:
        base = field.split(":")[0]
        assert base in marker_map, f"预览字段未纳入一致性断言：{field}"

    captured, _canned, _tmp = ai_env
    tid = parse_tid(client)
    assert client.post("/api/ai/column-advice", json={"thread_id": tid}).status_code == 200
    body = json.dumps(captured["messages"][0], ensure_ascii=False)
    for field in preview["fields"]:
        base = field.split(":")[0]
        for marker in marker_map[base]:
            assert marker in body, f"预览声称会发送 {field}，但实际请求体无对应字段（缺 {marker}）"
    # 预览声明「永不发送」的项，实际请求体也不得出现
    never = json.dumps(preview["never_sent"], ensure_ascii=False)
    assert "原始单元格值" in never
    for marker in RAW_MARKERS:
        assert marker not in body
    assert preview["key_configured"] is False


def test_ac19_4_cache_hit_on_second_call(client, ai_env):
    """相同输入第二次调用命中缓存（cached=true），且不再走网络跳。"""
    captured, _canned, _tmp = ai_env
    tid = parse_tid(client)
    first = client.post("/api/ai/column-advice", json={"thread_id": tid}).json()
    second = client.post("/api/ai/column-advice", json={"thread_id": tid}).json()
    assert first["cached"] is False and second["cached"] is True
    assert captured["calls"] == 2          # complete 被调用两次
    assert len(captured["payloads"]) == 1  # 但只有第一次真正构造了请求体（第二次缓存命中）


def test_ac19_5_ledger_fields_complete_and_value_free(client, ai_env):
    """台账字段齐备且不含数据值（grep 断言）。"""
    _captured, _canned, tmp_path = ai_env
    tid = parse_tid(client)
    client.post("/api/ai/column-advice", json={"thread_id": tid})
    lines = ledger_lines(tmp_path)
    assert lines, "必须落台账"
    required = {"ts", "purpose", "provider", "model", "prompt_version", "input_digest",
                "input_fields", "value_sharing", "bytes_sent", "cached", "schema_ok",
                "degraded", "reason", "latency_ms"}
    for entry in lines:
        assert required <= set(entry.keys()), f"台账字段缺失：{required - set(entry.keys())}"
        assert entry["purpose"] == "column_advice"
        assert entry["prompt_version"] == "ai-p1"
        raw = json.dumps(entry, ensure_ascii=False)
        for marker in RAW_MARKERS:
            assert marker not in raw, f"台账泄露数据值：{marker}"
        assert "api_key" not in raw and "sk-" not in raw
        assert "/Users/" not in raw  # 禁绝对路径


def test_ac20_5_no_click_no_call(client, ai_env):
    """未点开不调用 —— 只跑常规流程（体检/规划/执行），台账不得出现 AI 记录。"""
    _captured, _canned, tmp_path = ai_env
    tid = parse_tid(client)
    run_clean(client, tid)
    assert ledger_lines(tmp_path) == []


# ---------------------------------------------------------------------------
# 列语义建议
# ---------------------------------------------------------------------------


def test_ac20_1_advice_within_controlled_enum_and_op_catalog(client, ai_env):
    """语义类型 ∈ 受控枚举；建议算子 ∈ 既有算子目录。"""
    from app.ai.config import SEMANTIC_TYPES
    from app.operations.base import OperationRegistry
    tid = parse_tid(client)
    r = client.post("/api/ai/column-advice", json={"thread_id": tid, "columns": ["金额"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["degraded"] is False
    assert body["advice"], "应给出建议"
    for item in body["advice"]:
        assert item["semantic_type"] in SEMANTIC_TYPES
        assert item["evidence"], "必须给出依据"
        assert item["rationale"]
        assert 0.0 <= float(item["confidence"]) <= 1.0
        for op in item["suggested_ops"]:
            assert OperationRegistry.get(op["op"]) is not None, f"算子不在目录内：{op['op']}"


def test_ac20_1_unknown_column_request_falls_back(client, ai_env):
    """请求了不存在的列 → 不得抛 500，降级为无建议。"""
    tid = parse_tid(client)
    r = client.post("/api/ai/column-advice", json={"thread_id": tid, "columns": ["不存在列"]})
    assert r.status_code == 200, r.text
    assert r.json()["degraded"] is True


def test_ac20_2_bad_schema_retries_once_then_degrades(client, ai_env):
    """输出越界类型 → 重试 1 次 → degraded=true，且不产生任何数据改动。"""
    captured, canned, _tmp = ai_env
    tid = parse_tid(client)
    before_stage = stage_of(client, tid)
    canned["value"] = {"advice": [{"column": "金额", "semantic_type": "自造类型"}]}
    r = client.post("/api/ai/column-advice", json={"thread_id": tid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["degraded"] is True and body["reason"] == "bad_schema"
    assert body["advice"] == []
    assert captured["calls"] == 2, "必须恰好重试 1 次"
    # 不产生任何数据改动（阶段未推进）
    assert stage_of(client, tid) == before_stage


def test_ac20_2_unreachable_degrades_not_500(client, monkeypatch, no_ai_env, tmp_path):
    """通道不可达 → 200 + degraded=unreachable（绝不 500）。"""
    from app.ai import client as ai_client
    monkeypatch.setenv("CLEAN_AI_ENABLED", "true")
    monkeypatch.setenv("CLEAN_AI_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CLEAN_AI_BASE_URL", "http://127.0.0.1:65534/v1")
    monkeypatch.setenv("CLEAN_AI_MODEL", "fake-model")
    monkeypatch.setattr(ai_client, "_cache_dir", lambda: tmp_path / "ai-cache")
    tid = parse_tid(client)
    r = client.post("/api/ai/column-advice", json={"thread_id": tid})
    assert r.status_code == 200, r.text
    assert r.json()["degraded"] is True
    assert r.json()["reason"] in ("unreachable", "timeout")


def test_ac20_unknown_thread_404(client, ai_env):
    """接口契约：未知 thread_id → 404（与全站一致）。"""
    for path in ("/api/ai/column-advice", "/api/ai/report-explain", "/api/ai/accept-advice"):
        r = client.post(path, json={"thread_id": "t_not_exist", "column": "金额",
                                    "op": "cell_amount_clean"})
        assert r.status_code == 404, f"{path} 未按契约返回 404：{r.status_code}"


def test_b6_body_secret_rejected(client, ai_env):
    """四个端点一律不接收密钥字段，收到即 400。"""
    tid = parse_tid(client)
    r = client.post("/api/ai/column-advice", json={"thread_id": tid, "api_key": "sk-x"})
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "FORBIDDEN_BODY_KEY"
    r = client.post("/api/ai/report-explain", json={"thread_id": tid, "token": "x"})
    assert r.status_code == 400


def test_ac20_3_accept_advice_produces_replayable_recipe(client, ai_env, tmp_path):
    """人点「加入配方」→ 标准配方步骤，与手工规划同构、可重放（输出逐字节一致）。"""
    from app.ai.service import AiService
    tid = parse_tid(client)
    built = AiService().build_recipe_step(["订单号", "客户", "金额", "备注"],
                                          "金额", "cell_amount_clean", {})
    assert built["ok"] is True
    r = client.post("/api/ai/accept-advice", json={
        "thread_id": tid, "column": "金额", "op": "cell_amount_clean", "params": {},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["appended"] is True
    assert body["recipe_step_index"] == 0
    assert body["step"] == {"op": "cell_amount_clean", "params": {"column": "金额"}}
    # 同参重复点击 → 幂等，不重复追加
    again = client.post("/api/ai/accept-advice", json={
        "thread_id": tid, "column": "金额", "op": "cell_amount_clean", "params": {},
    }).json()
    assert again["appended"] is False and again["reason"] == "duplicate"
    assert again["recipe_step_index"] == 0
    # 可重放：AI 追加的配方直接确认 + 执行跑通
    confirm_execute_only(client, tid)
    ai_path = export_to(client, tid, tmp_path / "ai")

    # 对照组：同一条步骤走「手工规划」路径（既有契约），输出应逐字节一致
    tid2 = parse_tid(client)
    run_clean(client, tid2, ops=[{"op": "cell_amount_clean", "params": {"column": "金额"}}],
              name="manual-plan")
    manual_path = export_to(client, tid2, tmp_path / "manual")

    with open(ai_path, "rb") as fh:
        ai_bytes = fh.read()
    with open(manual_path, "rb") as fh:
        manual_bytes = fh.read()
    assert ai_bytes == manual_bytes, "AI 追加的配方与手工规划不同构"
    assert ai_bytes, "导出不得为空"


def test_ac20_1b_masked_column_params_are_unmasked(client, ai_env):
    """回归：敏感列的建议参数里若带遮罩列名，必须还原为真名，否则「加入配方」必 400。

    默认配置下「客户」命中敏感词 → 外发为「列#1」；模型只能看到遮罩名，它返回的
    建议参数同样是「列#1」。修复前后端只还原 advice.column、漏了 suggested_ops
    [].params，用户点「加入配方」→ 400 params_invalid（敏感列必现）。
    """
    captured, canned, _tmp = ai_env
    tid = parse_tid(client)
    canned["value"] = {
        "advice": [{
            "column": "列#1",  # 「客户」的外发遮罩名
            "semantic_type": "自由文本",
            "evidence": ["PLAIN_TEXT 100%"],
            "suggested_ops": [{"op": "cell_trim", "params": {"column": "列#1"}}],
            "rationale": "客户列存在首尾空白。",
            "confidence": 0.6,
        }]
    }
    r = client.post("/api/ai/column-advice", json={"thread_id": tid, "columns": [SENSITIVE_COL]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["degraded"] is False, body
    item = body["advice"][0]
    assert item["column"] == SENSITIVE_COL, "建议列名必须还原为真名"
    assert item["suggested_ops"][0]["params"]["column"] == SENSITIVE_COL, \
        "建议参数里的列名必须还原为真名（否则 accept-advice 400）"
    # 带着后端返回的建议原样点「加入配方」→ 必须 200（修复前此处 400）
    acc = client.post("/api/ai/accept-advice", json={
        "thread_id": tid, "column": item["column"],
        "op": item["suggested_ops"][0]["op"],
        "params": item["suggested_ops"][0]["params"],
    })
    assert acc.status_code == 200, acc.text
    assert acc.json()["appended"] is True
    assert acc.json()["step"]["params"]["column"] == SENSITIVE_COL


def test_accept_advice_400_reasons(client, ai_env):
    """边界：未知算子 / 未知列 → 400 且给出具体 code。"""
    tid = parse_tid(client)
    r = client.post("/api/ai/accept-advice", json={"thread_id": tid, "column": "金额",
                                                   "op": "not_an_op", "params": {}})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "unknown_op"
    r = client.post("/api/ai/accept-advice", json={"thread_id": tid, "column": "不存在",
                                                   "op": "cell_amount_clean", "params": {}})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "column_not_found"


def test_ac20_4c_unconfirmed_advice_changes_nothing(client, ai_env, tmp_path):
    """反例：AI 建议未经人确认 ⇒ 配方零变化、输出零变化。"""
    tid = parse_tid(client)
    run_clean(client, tid, ops=[{"op": "row_dedupe", "params": {"subset": ["订单号"]}}])
    first_path = export_to(client, tid, tmp_path / "before")
    with open(first_path, "rb") as fh:
        first_bytes = fh.read()

    # 只看建议、不点「加入配方」，也不导出
    assert client.post("/api/ai/column-advice", json={"thread_id": tid}).status_code == 200
    assert client.post("/api/ai/report-explain", json={"thread_id": tid}).status_code == 200
    second_path = export_to(client, tid, tmp_path / "after")
    with open(second_path, "rb") as fh:
        second_bytes = fh.read()
    assert first_bytes == second_bytes, "未经确认的建议不得影响任何输出"


# ---------------------------------------------------------------------------
# 人话版
# ---------------------------------------------------------------------------


def test_ac21_1_and_ac21_2_explain_readonly_with_disclaimer(client, ai_env, tmp_path):
    """人话摘要只读、不写入结果字段；disclaimer 非空；导出默认不含该文本。"""
    tid = parse_tid(client)
    run_clean(client, tid)
    r = client.post("/api/ai/report-explain", json={"thread_id": tid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["disclaimer"], "disclaimer 必须非空"
    assert "AI 生成" in body["disclaimer"]
    assert body["text"]
    # 只读：报告中不出现该文本
    report = client.post("/api/report", json={"thread_id": tid})
    assert report.status_code == 200, report.text
    assert body["text"] not in json.dumps(report.json(), ensure_ascii=False)
    # 导出默认不含 AI 文本
    exp_path = export_to(client, tid, tmp_path)
    with open(exp_path, "r", encoding="utf-8") as fh:
        assert body["text"].splitlines()[0] not in fh.read()


def test_ac21_degraded_explain_falls_back_deterministic(client, ai_env):
    """模型输出不合规 → 降级为确定性文本（永不缺席、永不 500）。"""
    _captured, canned, _tmp = ai_env
    tid = parse_tid(client)
    run_clean(client, tid)
    canned["explain"] = {"nope": 1}  # 坏结构 → 重试 1 次仍不合规 → 降级
    r = client.post("/api/ai/report-explain", json={"thread_id": tid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["degraded"] is True and body["reason"] == "bad_schema"
    assert body["text"]      # 确定性兜底文本（永不缺席）
    assert body["disclaimer"]


def test_ac21_3_report_explain_cache_hit(client, ai_env):
    """人话版缓存命中行为正确。"""
    tid = parse_tid(client)
    run_clean(client, tid)
    first = client.post("/api/ai/report-explain", json={"thread_id": tid}).json()
    second = client.post("/api/ai/report-explain", json={"thread_id": tid}).json()
    assert first["cached"] is False and second["cached"] is True
    assert first["text"] == second["text"]


def test_explain_disabled_returns_deterministic_text(client, no_ai_env):
    """未启用：直接返回确定性文本 + degraded=disabled，不构造任何请求。"""
    tid = parse_tid(client)
    run_clean(client, tid)
    r = client.post("/api/ai/report-explain", json={"thread_id": tid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["degraded"] is True and body["reason"] == "disabled"
    assert body["text"] and body["disclaimer"] == "AI 生成，数值以上方表格为准"
