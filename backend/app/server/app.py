"""清洗项目本地服务：12 条接口（3 实测 + 9 规划）。

- 仅绑定 127.0.0.1（本地单机，数据不出本机）。
- 运行态：内存 holder + SQLite 审计（仅元数据）。
"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from ..detectors.base import DetectorRegistry
from ..engine.engine import (begin_verify_round, build_plan, check_coverage, confirm_plan,
                             execute_recipe, record_override)
from ..graph.pipeline import NODE_ORDER, GraphIO, build_pipeline
from langgraph.types import Command
from ..export.exporter import ExportError, export_data, export_issues_csv, export_issues_summary_csv
from ..parsing.parser import ParseError, parse_stream
from ..persistence.store import Store
from ..recipe.engine import export_recipe_json, sign_recipe, validate_recipe
from ..report.reporter import ISSUE_LABELS, build_report, render_json, render_markdown
from ..server.samples import enrich_profile
from ..state import CleanState
from ..verify.verifier import compare

# AI 辅助层：只在 server 层接线；执行链（graph/engine/operations/verify）
# 不 import 本包（静态守卫断言）。
from ..ai.config import FORBIDDEN_BODY_KEYS, AiConfig
from ..ai.service import AiService

# ---------------------------------------------------------------------------
# 请求/响应模型（字段级 schema 与接口契约对齐）
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    version: str
    schema_id: str


class ParseRequest(BaseModel):
    file_name: str
    file_type: str
    file_size: int
    file_hash: str = ""
    content_b64: str = ""
    thread_id: str = ""


class EdaRequest(BaseModel):
    thread_id: str


class PlanRequest(BaseModel):
    thread_id: str
    operations: List[Dict[str, Any]] = Field(default_factory=list)
    recipe_name: str = "auto-plan"


class ConfirmOverride(BaseModel):
    """越权放行（契约，定死）：ack 必须为真 + 必填说明（≥5 字）+ 被跳过的 issue 名单。"""
    ack: bool = False
    skipped: List[str] = Field(default_factory=list)
    note: str = ""


class ConfirmRequest(BaseModel):
    thread_id: str
    approve: bool
    reason: str = ""
    override: Optional[ConfirmOverride] = None  # 新增可选字段，既有 approve/reason 不变


class ExecuteRequest(BaseModel):
    thread_id: str


class VerifyRequest(BaseModel):
    thread_id: str


class ReportRequest(BaseModel):
    thread_id: str
    format: str = "json"  # json | md


class ExportRequest(BaseModel):
    thread_id: str
    format: str = "xlsx"  # csv | xlsx | ods | pdf | json | sql | template
    out_dir: str = ""
    table_name: str = "cleaned"  # sql
    encoding: str = "utf-8"  # template
    line_ending: str = "lf"  # template: lf | crlf
    template_placeholders: Dict[str, str] = Field(default_factory=dict)  # template
    include_attachments: bool = True  # 问题明细/汇总 CSV + 配方 JSON


class RunRequest(BaseModel):
    """全流程自动化：parse（可省）→ eda → plan → confirm → execute → verify → report。"""
    file_name: str = ""
    file_type: str = ""
    file_size: int = 0
    file_hash: str = ""
    content_b64: str = ""
    operations: List[Dict[str, Any]] = Field(default_factory=list)
    auto_confirm: bool = False
    out_dir: str = ""
    export_format: str = "xlsx"


class RecipeImportRequest(BaseModel):
    thread_id: str = ""
    recipe_json: Dict[str, Any]


# --- AI 辅助层请求模型 -----------------------------------
# 说明：统一 extra="allow" + 手工检查 model_extra —— 端点一律不接收密钥字段（收到即 400）。
class AiColumnAdviceRequest(BaseModel):
    """列语义与方案建议。columns 省略 = 全部列。"""
    model_config = ConfigDict(extra="allow")
    thread_id: str
    columns: Optional[List[str]] = None


class AiReportExplainRequest(BaseModel):
    """体检报告人话版。"""
    model_config = ConfigDict(extra="allow")
    thread_id: str


class AiAcceptAdviceRequest(BaseModel):
    """把人工确认过的建议追加为配方步骤（**不写数据，只追加配方**）。"""
    model_config = ConfigDict(extra="allow")
    thread_id: str
    column: str
    op: str
    params: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 运行态
# ---------------------------------------------------------------------------


def _stamp_suffix() -> str:
    now = datetime.now()
    return f"{now.year}{now.month:02d}{now.day:02d}_{now.hour:02d}{now.minute:02d}{now.second:02d}"


def _now_stamp() -> str:
    now = datetime.now()
    return f"{now.year}-{now.month:02d}-{now.day:02d} {now.hour:02d}:{now.minute:02d}:{now.second:02d}"


class Runtime:
    """线程状态持有器（单进程内使用；数据引用落盘以支持跨会话重放）。"""

    def __init__(self, db_path: str):
        self._lock = threading.Lock()
        self.store = Store(db_path)
        self._threads: Dict[str, Dict[str, Any]] = {}
        self._graphs: Dict[str, Any] = {}
        self._data_dir = os.path.join(os.path.dirname(db_path), "threads")
        os.makedirs(self._data_dir, exist_ok=True)
        # 检查点持久化（跨会话重放）：与审计库同文件的不同表（checkpoints / writes）
        from langgraph.checkpoint.sqlite import SqliteSaver
        self.checkpointer = SqliteSaver(sqlite3.connect(db_path, check_same_thread=False))

    def create_thread(self, source: Dict[str, Any]) -> str:
        tid = f"clean-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        state = CleanState(thread_id=tid, source=source)
        with self._lock:
            self._threads[tid] = {"state": state, "before": None, "after": None}
        self.store.start_thread(tid, source)
        self._persist(tid)
        return tid

    def get(self, tid: str) -> Dict[str, Any]:
        with self._lock:
            entry = self._threads.get(tid)
            if entry is None:
                raise KeyError(tid)
            return entry

    def rehydrate(self, tid: str) -> bool:
        """跨会话重放：内存无该线程时用落盘引用重建；执行进度由 SQLite 检查点恢复。"""
        with self._lock:
            if tid in self._threads:
                return True
            path = os.path.join(self._data_dir, f"{tid}.json")
            if not os.path.exists(path):
                return False
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            try:
                state = CleanState(**payload["state"])
            except Exception:
                return False
            self._threads[tid] = {"state": state, "before": payload.get("before"),
                                  "after": payload.get("after")}
        return True

    def update(self, tid: str, **kwargs: Any) -> None:
        with self._lock:
            entry = self._threads[tid]
            entry.update(kwargs)
        self._persist(tid)

    def state(self, tid: str) -> CleanState:
        return self.get(tid)["state"]

    def list_threads(self) -> List[Dict[str, Any]]:
        return self.store.list_threads()

    def _persist(self, tid: str) -> None:
        """数据引用落盘（本机内部流转，数据不出本机）：服务重启后可续跑。

        并发安全（缺陷修复）：快照在锁内取；临时文件名带 pid + 线程标识，避免同一会话的
        并发请求（前端重复提交 / 重挂载）写同一个 `<tid>.json.tmp`，导致其中一方在
        os.replace 时因对方已移走临时文件而抛 FileNotFoundError（表现为 HTTP 500）。
        """
        with self._lock:
            entry = self._threads.get(tid)
            if entry is None:
                return
            payload = {"before": entry["before"], "after": entry["after"],
                       "state": entry["state"].model_dump()}
        path = os.path.join(self._data_dir, f"{tid}.json")
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            raise


_guards: Dict[str, threading.Lock] = {}
_guards_lock = threading.Lock()


def _thread_guard(thread_id: str) -> threading.Lock:
    """按 thread_id 取进程内互斥锁（缺陷修复）：同一会话的重复提交排队执行而非并发改写，
    既避免重复跑清洗，也避免落盘 / 审计写入相互踩踏。"""
    with _guards_lock:
        return _guards.setdefault(thread_id, threading.Lock())


def _new_runtime() -> Runtime:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    db_dir = os.path.join(repo_root, "data")
    return Runtime(os.path.join(db_dir, "clean-runs.db"))


def create_app() -> FastAPI:
    app = FastAPI(title="本地数据清洗台", version="0.1.0")
    # 前端 dev 服务器（127.0.0.1:5173）与本地服务（127.0.0.1:8321）端口不同，
    # 属跨源请求；仅放行环回来源，不引入任何外部来源（红线：数据不出本机）。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
        max_age=600,
    )
    rt = _new_runtime()

    def _get_entry(tid: str) -> Dict[str, Any]:
        try:
            return rt.get(tid)
        except KeyError:
            if rt.rehydrate(tid):  # 跨会话重放：内存无该线程时从落盘引用重建
                return rt.get(tid)
            raise HTTPException(status_code=404, detail=f"thread {tid} 不存在")

    # --- 实测 1：健康检查 -------------------------------------------------
    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version="0.1.0", schema_id="clean-recipe/v1")

    # --- 实测 2：发起体检（EDA） ------------------------------------------
    @app.post("/api/eda")
    def eda(req: EdaRequest) -> Dict[str, Any]:
        entry = _get_entry(req.thread_id)
        if entry["before"] is None:
            raise HTTPException(status_code=400, detail="先 /api/parse 再体检")
        state = entry["state"]
        profile = DetectorRegistry.run_all(entry["before"]["columns"], entry["before"]["rows"], verbosity=1)
        # 问题命中行附"样本值"（后端抽取 + 脱敏，只增字段）
        enrich_profile(profile, entry["before"]["columns"], entry["before"]["rows"])
        state.profile = profile
        state.stage = "eda"
        rt.store.append_node_run(req.thread_id, "eda", "COMPLETED", _now_stamp(), _now_stamp())
        return {"thread_id": req.thread_id, "profile": profile}

    # --- 实测 3：一键清洗（parse→eda→plan→HITL→execute→verify→report→export）---
    @app.post("/api/clean")
    def clean(req: RunRequest) -> Dict[str, Any]:
        return _run_pipeline(rt, req, mode="clean")

    # --- 上传并解析 -------------------------------------------------
    @app.post("/api/parse")
    def parse(req: ParseRequest) -> Dict[str, Any]:
        # 带 thread_id 时先做存在性校验 —— 未知 tid 走 _get_entry → 404（原先 rt.update 抛
        # KeyError 冒泡成 500，是 12 个端点里唯一漏走守卫的入口）。
        # 校验点必须在 parse_stream 之前：不解析完才发现"线程不存在"。
        if req.thread_id:
            _get_entry(req.thread_id)
        try:
            result = parse_stream(req.file_name, req.file_type, req.file_size,
                                  req.file_hash, req.content_b64, req.thread_id or "pre")
        except ParseError as exc:
            raise HTTPException(status_code=400, detail=exc.message)
        tid = req.thread_id or rt.create_thread({"file_name": req.file_name, "file_type": req.file_type,
                                                 "file_size": req.file_size, "file_hash": req.file_hash})
        rt.update(tid, before={"columns": result.columns, "rows": result.rows})
        state = rt.state(tid)
        state.source = {"file_name": req.file_name, "file_type": req.file_type,
                        "file_size": req.file_size, "file_hash": req.file_hash}
        state.data_ref = result.data_ref
        state.stage = "parsed"
        rt.store.append_node_run(tid, "parse", "COMPLETED", _now_stamp(), _now_stamp())
        return {
            "thread_id": tid,
            "columns": result.columns,
            "row_count": result.row_count,
            "col_count": result.col_count,
            "parsing_report": result.parsing_report,
        }

    # --- 生成配方 ---------------------------------------------------
    @app.post("/api/plan")
    def plan(req: PlanRequest) -> Dict[str, Any]:
        entry = _get_entry(req.thread_id)
        state = entry["state"]
        recipe = {
            "schema_id": "clean-recipe/v1",
            "name": req.recipe_name,
            "source": {"thread_id": req.thread_id, "file_name": state.source.get("file_name", "")},
            "operations": req.operations,
        }
        try:
            result = build_plan(state, recipe, columns=entry["before"]["columns"])
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        rt.store.update_thread(req.thread_id, "PLANNED", recipe)
        rt.store.append_node_run(req.thread_id, "plan", "COMPLETED", _now_stamp(), _now_stamp())
        return {"thread_id": req.thread_id, **result}

    # --- 人工确认门 --------------------------------------------------
    @app.post("/api/confirm")
    def confirm(req: ConfirmRequest) -> Dict[str, Any]:
        entry = _get_entry(req.thread_id)
        state = entry["state"]
        override_record: Optional[Dict[str, Any]] = None
        plan_reason = req.reason
        if req.approve:
            # 覆盖校验下沉为后端最终闸门（前端 riskGate 只是体验层，直调接口不得绕过）
            coverage = check_coverage(state, entry["before"])
            if not coverage["covered"]:
                ack = bool(req.override and req.override.ack)
                note = (req.override.note if req.override else "") or ""
                if not ack:
                    raise HTTPException(status_code=409, detail={
                        "code": "COVERAGE_BLOCKED",
                        "message": f"{coverage['uncovered_high_count']} 项体检高危问题未被当前配方覆盖（未达标）；"
                                   f"如需强行放行，请带 override.ack=true + 说明（≥5 字）",
                        "uncovered_high": coverage["uncovered_high"],
                    })
                if len(note.strip()) < 5:
                    raise HTTPException(status_code=409, detail={
                        "code": "OVERRIDE_NOTE_REQUIRED",
                        "message": "越权放行必须填写跳过原因（≥5 字），不得空放行",
                        "uncovered_high": coverage["uncovered_high"],
                    })
                # 留痕：记录跳过项 + 说明 + 时间；confirm_reason 记 override.note
                override_record = record_override(state, coverage, note, req.override.skipped)
                plan_reason = note
        try:
            result = confirm_plan(state, req.approve, plan_reason)
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        rt.store.append_node_run(req.thread_id, "confirm", "COMPLETED", _now_stamp(), _now_stamp())
        rt.update(req.thread_id)
        resumed = _resume_pipeline(rt, req.thread_id, req.approve, plan_reason)
        payload = {**result, "override": override_record}
        if resumed:  # 该线程由图编排且挂起在人工门：注入决策恢复执行
            return {**payload, **resumed}
        return payload

    # --- 执行配方 ----------------------------------------------------
    @app.post("/api/execute")
    def execute(req: ExecuteRequest) -> Dict[str, Any]:
        # 同会话串行 + 幂等（缺陷修复）：前端重复提交（含 React 18 StrictMode 双挂载）
        # 不再并发改写同一会话，也不会重复跑清洗或写第 2 条 execute 节点。
        with _thread_guard(req.thread_id):
            entry = _get_entry(req.thread_id)
            state = entry["state"]
            if entry["before"] is None:
                raise HTTPException(status_code=400, detail="先 /api/parse")
            if state.stage == "executed" and entry["after"] is not None:
                # 同一配方已执行完成：直接复用结果（重入/重试均返回 200，不再产生重复节点）
                return {
                    "columns": entry["after"]["columns"],
                    "rows": entry["after"]["rows"],
                    "transform_log": state.transform_log,
                    "data_ref": state.data_ref,
                }
            try:
                result = execute_recipe(state, entry["before"]["columns"], entry["before"]["rows"])
            except Exception as exc:
                raise HTTPException(status_code=409, detail=str(exc))
            rt.update(req.thread_id, after={"columns": result["columns"], "rows": result["rows"]})
            rt.store.update_thread(req.thread_id, "EXECUTED")
            rt.store.append_node_run(req.thread_id, "execute", "COMPLETED", _now_stamp(), _now_stamp())
            return result

    # --- 前后校验 -----------------------------------------------------
    @app.post("/api/verify")
    def verify(req: VerifyRequest) -> Dict[str, Any]:
        entry = _get_entry(req.thread_id)
        state = entry["state"]
        if entry["before"] is None or entry["after"] is None:
            raise HTTPException(status_code=400, detail="先 parse + execute")
        result = compare(entry["before"], entry["after"], profile=state.profile)
        verdict = begin_verify_round(state, result["passed"], result["metrics"], result["unmet"])
        # 缺陷修复②：校验指标更新后旧报告失效，报告屏须按新指标重建（避免内容停留在上一轮）。
        state.report = {}
        rt.store.append_node_run(req.thread_id, "verify_check", "COMPLETED", _now_stamp(), _now_stamp())
        return {"thread_id": req.thread_id, **result, **verdict}

    # --- 生成报告 -----------------------------------------------------
    @app.post("/api/report")
    def report(req: ReportRequest) -> Dict[str, Any]:
        entry = _get_entry(req.thread_id)
        state = entry["state"]
        # 缺陷修复②（「三、质量对比」为空）：报告依赖前后校验指标。若调用方尚未跑校验
        # （例如前端并发请求校验与报告），此处就地按 before/after 补算一次，杜绝指标恒为空。
        if not state.verify and entry["before"] is not None and entry["after"] is not None:
            cmp_result = compare(entry["before"], entry["after"], profile=state.profile)
            begin_verify_round(state, cmp_result["passed"], cmp_result["metrics"], cmp_result["unmet"])
        if not state.report:
            state.report = build_report(state, state.profile, state.verify, state.transform_log)
        rt.store.update_thread(req.thread_id, "REPORTED")
        rt.store.append_node_run(req.thread_id, "report_build", "COMPLETED", _now_stamp(), _now_stamp())
        if req.format == "md":
            return {"thread_id": req.thread_id, "format": "md", "content": render_markdown(state.report)}
        return {"thread_id": req.thread_id, "format": "json", "content": json.loads(render_json(state.report))}

    # --- 导出 --------------------------------------------------------
    @app.post("/api/export")
    def export(req: ExportRequest) -> Dict[str, Any]:
        entry = _get_entry(req.thread_id)
        state = entry["state"]
        if entry["after"] is None:
            raise HTTPException(status_code=400, detail="先 execute")
        out_dir = req.out_dir or os.path.join(os.path.expanduser("~"), "Desktop", "清洗导出")
        base_name = os.path.splitext(state.source.get("file_name", "clean"))[0]
        try:
            path = export_data(req.format, entry["after"]["columns"], entry["after"]["rows"], out_dir,
                               base_name, render_markdown(state.report) if state.report else None,
                               table_name=req.table_name, encoding=req.encoding,
                               line_ending=req.line_ending,
                               template_placeholders=req.template_placeholders,
                               meta={"thread_id": req.thread_id,
                                     "source": state.source,
                                     "recipe_id": state.recipe_id})
        except ExportError as exc:
            raise HTTPException(status_code=400, detail=exc.message)
        files = [path]
        if req.include_attachments:
            # 导出套件：问题明细 / 问题汇总 CSV + 配方 recipe.json 同批落盘
            files.append(export_issues_csv(state.profile, out_dir, base_name))
            files.append(export_issues_summary_csv(state.profile, out_dir, base_name))
            if state.rules_plan:
                recipe_path = os.path.join(out_dir, f"{base_name}_{_stamp_suffix()}_recipe.json")
                files.append(export_recipe_json(state.rules_plan, recipe_path))
        rt.store.append_export(req.thread_id, req.format, path)
        rt.store.append_node_run(req.thread_id, "export", "COMPLETED", _now_stamp(), _now_stamp())
        return {"thread_id": req.thread_id, "path": path, "format": req.format, "files": files}

    # --- 全流程自动化 -------------------------------------------------
    @app.post("/api/run")
    def run(req: RunRequest) -> Dict[str, Any]:
        return _run_pipeline(rt, req, mode="run")

    # --- 执行记录 / 进度查询 -----------------------------------------
    @app.get("/api/run/{run_id}")
    def run_status(run_id: str) -> Dict[str, Any]:
        """查询线程阶段与节点进度（前端轮询）。run_id 即 thread_id。"""
        entry = rt._threads.get(run_id)
        if entry is None:
            rt.rehydrate(run_id)  # 跨会话：从落盘引用重建线程视图
            entry = rt._threads.get(run_id)
        if entry is None and rt.store.get_thread(run_id) is None:
            raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
        stage = entry["state"].stage if entry is not None else "idle"
        recorded = {r["node_name"]: r for r in rt.store.list_node_runs(run_id)}
        nodes = [recorded.get(name, {"node_name": name, "attempt": 1, "status": "PENDING",
                                     "started_at": None, "ended_at": None})
                 for name in NODE_ORDER]
        return {"ok": True, "run_id": run_id, "stage": stage, "nodes": nodes}

    # --- 导入配方 ------------------------------------------------------
    @app.post("/api/recipe-import")
    def recipe_import(req: RecipeImportRequest) -> Dict[str, Any]:
        recipe = req.recipe_json
        errors = validate_recipe(recipe)
        if errors:
            raise HTTPException(status_code=400, detail="；".join(errors[:10]))
        tid = req.thread_id or rt.create_thread({"file_name": "recipe-import", "file_type": "recipe"})
        state = rt.state(tid)
        build_plan(state, recipe)
        return {"thread_id": tid, "recipe_id": state.recipe_id, "steps": len(recipe.get("operations", []))}

    # --- AI 辅助端点 --------------------------------------------------
    # 红线：这些端点只读体检与校验结果、只追加配方，永不改动任何数据值；
    # 红线：密钥只从环境变量（或仓库根 .env）读取，请求体出现密钥字段一律 400。

    def _ai_assert_no_secret(payload_keys: Any) -> None:
        """端点一律不收任何密钥字段，收到即 400（不落日志、不回显）。"""
        bad = [str(k) for k in (payload_keys or []) if str(k).lower() in FORBIDDEN_BODY_KEYS]
        if bad:
            raise HTTPException(status_code=400, detail={
                "code": "FORBIDDEN_BODY_KEY",
                "message": f"请求体不得包含密钥字段：{'、'.join(bad)}；密钥只从环境变量读取",
            })

    def _ai_column_labels(entry: Dict[str, Any]) -> Dict[str, str]:
        """报告摘要里出现的列名同样走脱敏（敏感列 → 列#n）。

        体检问题的 samples 里带的是**原始列名**，若原样塞进摘要，就会经通道
        外发列名——与本层「列名按 CLEAN_AI_COLUMN_NAME_SHARING 脱敏」的既有口径不一致，
        故此处统一映射后再交给 AiService。
        """
        columns = [str(c) for c in ((entry.get("before") or {}).get("columns") or [])]
        cfg = AiConfig()
        return {c: cfg.column_label(c, i + 1) for i, c in enumerate(columns)}

    def _ai_mask_text(text: Any, labels: Dict[str, str]) -> str:
        """把文本里出现的原始列名按映射替换为脱敏名（长名优先，避免子串误替换）。"""
        out = str(text if text is not None else "")
        for raw in sorted(labels, key=len, reverse=True):
            if raw:
                out = out.replace(raw, labels[raw])
        return out

    def _ai_report_summary(entry: Dict[str, Any]) -> Dict[str, Any]:
        """把运行态汇总成「只含确定性统计事实」的报告摘要（不含任何数据值）。"""
        state = entry["state"]
        labels = _ai_column_labels(entry)
        before = entry.get("before") or {}
        profile = state.profile if isinstance(state.profile, dict) else {}
        verify = state.verify if isinstance(state.verify, dict) else {}
        report = state.report if isinstance(state.report, dict) else {}
        sections = report.get("sections") if isinstance(report.get("sections"), dict) else {}
        sec1 = sections.get("1_profile") or {}
        sec3 = sections.get("3_quality") or {}
        sec4 = sections.get("4_unhandled") or {}
        overrides = getattr(state, "overrides", None) or {}
        issues: List[Dict[str, Any]] = []
        for it in (profile.get("issues") or [])[:20]:
            if not isinstance(it, dict):
                continue
            rows = it.get("rows") or []
            sample_col = ((it.get("samples") or [{}])[0] or {}).get("column")
            name = it.get("issue_name", "")
            issues.append({
                "id": name,
                "label": ISSUE_LABELS.get(name, name),
                "severity": it.get("severity"),
                "count": it.get("rows_total", len(rows)),
                "column": labels.get(str(sample_col), "全表") if sample_col else "全表",
            })
        return {
            "row_count": len(before.get("rows") or []),
            "column_count": len(before.get("columns") or []),
            "profile_conclusion": _ai_mask_text(sec1.get("conclusion") or "", labels),
            "quality_conclusion": _ai_mask_text(sec3.get("conclusion") or "", labels),
            "unhandled_count": sec4.get("count", len(sec4.get("unhandled") or [])),
            "issues": issues,
            "unmet": [_ai_mask_text(u, labels) for u in (verify.get("unmet") or [])],
            "overrides_ack": bool(isinstance(overrides, dict) and overrides.get("ack")),
        }

    @app.get("/api/ai/status")
    def ai_status(tid: str = "", thread_id: str = "", version: str = "",
                  probe: bool = False) -> Dict[str, Any]:
        """AI 通道可用性（永不 500；不可达 → reachable=false + last_error）。

        线程无关键参数：状态是「通道级」信息，不依赖任何 thread（要求不可达时
        仍返回 200），故 `tid` / `thread_id` 均可省略（两者都收，兼容既有调用口径）。

        `probe=false`（默认）只读缓存结果、不主动外呼；`probe=true`（设置页「测试连接」）才真探一次。
        """
        key = tid or thread_id
        try:
            return {"ok": True, "thread_id": key, **AiService().status(probe=bool(probe))}
        except Exception:
            return {"ok": True, "thread_id": key, "available": False, "enabled": False,
                    "reason": "AI 状态查询失败", "reachable": False, "last_error": "status_error"}

    @app.post("/api/ai/column-advice")
    def ai_column_advice(req: AiColumnAdviceRequest) -> Dict[str, Any]:
        """列语义与方案建议（未知线程 404；AI 失败 → 200 + degraded=true）。"""
        _ai_assert_no_secret(req.model_extra)
        entry = _get_entry(req.thread_id)
        before = entry.get("before") or {}
        columns = list(before.get("columns") or [])
        rows = [list(r) for r in (before.get("rows") or [])]
        result = AiService().column_advice(columns, rows, requested=req.columns)
        return {"ok": True, "thread_id": req.thread_id, **result}

    @app.post("/api/ai/report-explain")
    def ai_report_explain(req: AiReportExplainRequest) -> Dict[str, Any]:
        """体检报告人话版（AI 失败 → 200 + degraded=true，正文退确定性兜底）。"""
        _ai_assert_no_secret(req.model_extra)
        entry = _get_entry(req.thread_id)
        result = AiService().report_explain(_ai_report_summary(entry))
        return {"ok": True, "thread_id": req.thread_id, **result}

    @app.post("/api/ai/accept-advice")
    def ai_accept_advice(req: AiAcceptAdviceRequest) -> Dict[str, Any]:
        """把人工确认过的建议追加为配方步骤（**只追加配方，不写数据，不执行**）。"""
        _ai_assert_no_secret(req.model_extra)
        entry = _get_entry(req.thread_id)
        state = entry["state"]
        columns = list((entry.get("before") or {}).get("columns") or [])
        built = AiService().build_recipe_step(columns, req.column, req.op, req.params)
        if not built.get("ok"):
            # 400 契约：code ∈ unknown_op / params_invalid / column_not_found（与算子契约一致）
            raise HTTPException(status_code=400, detail={
                "code": built.get("error"),
                "message": built.get("detail") or "建议步骤未通过既有算子契约校验",
            })
        step = built["step"]
        current = state.rules_plan if isinstance(state.rules_plan, dict) else {}
        ops = list(current.get("operations") or [])
        for idx, existing in enumerate(ops):
            if isinstance(existing, dict) and existing.get("op") == step["op"] \
                    and existing.get("params") == step["params"]:
                # 幂等：同名同参步骤已存在 → 不重复追加，回既有位置
                return {"ok": True, "thread_id": req.thread_id, "appended": False,
                        "reason": "duplicate", "recipe_step_index": idx,
                        "step": step, "steps": len(ops)}
        ops.append(step)
        recipe = dict(current) if current.get("schema_id") else {
            "schema_id": "clean-recipe/v1",
            "name": "AI 辅助建议配方",
            "source": {"thread_id": req.thread_id,
                       "file_name": state.source.get("file_name", "")},
        }
        recipe["operations"] = ops
        sign_recipe(recipe)
        try:
            build_plan(state, recipe, columns=columns)  # 统一口径校验 + 落 state.rules_plan
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        rt.store.update_thread(req.thread_id, "PLANNED", recipe)
        rt.store.append_node_run(req.thread_id, "ai_accept_advice", "COMPLETED",
                                 _now_stamp(), _now_stamp())
        return {"ok": True, "thread_id": req.thread_id, "appended": True,
                "recipe_step_index": len(ops) - 1, "step": step, "steps": len(ops)}

    return app


def _graph_io(rt: Runtime, tid: str) -> GraphIO:
    """构造线程的图 IO 适配器：清洗前/后引用 + 清洗副本落盘 + 节点执行埋点。"""

    def _before() -> Any:
        return rt.get(tid)["before"]

    def _after() -> Any:
        entry = rt.get(tid)
        return entry["after"] or entry["before"]

    return GraphIO(
        load_fn=_before,
        load_after_fn=_after,
        save_fn=lambda data: rt.update(tid, after=data),
        store=rt.store,
        record_fn=lambda node, status, started, ended, err: rt.store.append_node_run(
            tid, node, status, started, ended, err),
    )


def _pipeline_graph(rt: Runtime, tid: str) -> Any:
    """取线程的编排图（首次构建并编译；检查点由 SqliteSaver 持久化，支持跨会话重放）。"""
    graph = rt._graphs.get(tid)
    if graph is None:
        graph = build_pipeline(_graph_io(rt, tid), checkpointer=rt.checkpointer)
        rt._graphs[tid] = graph
    return graph


_STATE_FIELDS = ("stage", "confirmed", "confirm_reason", "retry_count", "profile",
                 "rules_plan", "recipe_id", "transform_log", "verify", "report",
                 "signature_check", "data_ref", "errors", "overrides")


def _sync_state(state: CleanState, data: Any) -> None:
    """图内 state 为副本，执行后回写线程状态，供后续接口与进度查询读取。"""
    if not isinstance(data, dict):
        return
    for field in _STATE_FIELDS:
        if field in data:
            setattr(state, field, data[field])


def _resume_pipeline(rt: Runtime, tid: str, approve: bool, reason: str) -> Optional[Dict[str, Any]]:
    """线程由图编排且挂起在人工门时，注入决策恢复执行（中断恢复 / 跨会话重放）。

    无挂起（细粒度接口路径）返回 None；跨会话时从 SQLite 检查点重建图后恢复。
    """
    graph = rt._graphs.get(tid)
    if graph is None:
        if rt.store.get_thread(tid) is None:
            return None
        graph = _pipeline_graph(rt, tid)
    cfg = {"configurable": {"thread_id": tid}}
    try:
        snapshot = graph.get_state(cfg)
    except Exception:
        return None
    if not snapshot.next:
        return None
    out = graph.invoke(Command(resume={"approve": approve, "reason": reason}), cfg)
    state = rt.state(tid)
    # 留痕（缺陷修复）：越权放行记录写在服务层 state 上，而图内 state 是副本 →
    # 图内 report_build 节点构建报告时看不到 override，`_sync_state` 回写还会把它抹掉，
    # 结果是 /api/run、/api/clean 这条"图编排"路径的报告丢掉「经用户确认未处理」标注与
    # `3_quality.overrides`（细粒度接口路径不受影响）。此处回填记录并按新记录重建报告。
    prior_overrides = dict(getattr(state, "overrides", None) or {})
    _sync_state(state, out)
    if prior_overrides:
        state.overrides = prior_overrides
        if state.report:
            state.report = build_report(state, state.profile, state.verify, state.transform_log)
    rt.update(tid)
    rt.store.update_thread(tid, state.stage.upper() if state.stage else "RESUMED")
    return {"stage": state.stage, "resumed": True}


def _run_pipeline(rt: Runtime, req: RunRequest, mode: str) -> Dict[str, Any]:
    """run / clean 共用：LangGraph 图驱动（parse → eda → plan → confirm → execute
    → verify_check → report_build → export），人工门在 confirm 节点挂起等待决策。"""
    tid = getattr(req, "thread_id", "") or ""
    if req.file_name and req.content_b64:
        try:
            result = parse_stream(req.file_name, req.file_type, req.file_size,
                                  req.file_hash, req.content_b64, tid or "pre")
        except ParseError as exc:
            raise HTTPException(status_code=400, detail=exc.message)
        tid = tid or rt.create_thread({"file_name": req.file_name, "file_type": req.file_type,
                                       "file_size": req.file_size, "file_hash": req.file_hash})
        rt.update(tid, before={"columns": result.columns, "rows": result.rows})
        state = rt.state(tid)
        state.source = {"file_name": req.file_name, "file_type": req.file_type,
                        "file_size": req.file_size, "file_hash": req.file_hash}
        state.data_ref = result.data_ref
        state.stage = "parsed"
    elif tid not in rt._threads and not rt.rehydrate(tid):
        raise HTTPException(status_code=404, detail=f"thread {tid} 不存在")

    entry = rt.get(tid)
    state = entry["state"]
    if req.operations:
        state.rules_plan = {
            "schema_id": "clean-recipe/v1",
            "name": "auto-plan",
            "source": {"thread_id": tid, "file_name": state.source.get("file_name", "")},
            "operations": req.operations,
        }

    graph = _pipeline_graph(rt, tid)
    cfg = {"configurable": {"thread_id": tid}}
    out = graph.invoke(state, cfg)  # 挂起在人工门（无自动确认时）
    _sync_state(state, out)
    rt.update(tid)  # 落盘挂起态，支持跨会话（新进程）恢复

    if req.auto_confirm and not state.confirmed:
        # 自动确认也要过覆盖校验 —— 未覆盖高危项时不得由 auto 路径越权放行
        coverage = check_coverage(state, entry["before"])
        if coverage["covered"]:
            out = graph.invoke(Command(resume={"approve": True, "reason": "auto-run"}), cfg)
            _sync_state(state, out)
            rt.update(tid)
        else:
            rt.store.update_thread(tid, "PLANNED", state.rules_plan)
            rt.store.append_node_run(tid, "confirm", "AWAITING_HITL", _now_stamp(), None)
            return {"thread_id": tid, "stage": "awaiting_confirm", "code": "COVERAGE_BLOCKED",
                    "message": f"覆盖校验未通过：{coverage['uncovered_high_count']} 项体检高危问题未被当前配方覆盖；"
                               f"自动确认已停止，请走 /api/confirm（如需放行带 override.ack + 说明）",
                    "uncovered_high": coverage["uncovered_high"],
                    "recipe": state.rules_plan, "profile": state.profile}

    if state.stage == "awaiting_confirm" and not state.confirmed:
        rt.store.update_thread(tid, "PLANNED", state.rules_plan)
        rt.store.append_node_run(tid, "confirm", "AWAITING_HITL", _now_stamp(), None)
        return {"thread_id": tid, "stage": "awaiting_confirm",
                "message": "配方待人工确认（/api/confirm）",
                "recipe": state.rules_plan, "profile": state.profile}

    rt.store.update_thread(tid, state.stage.upper() if state.stage else "RUNNING")
    return {
        "thread_id": tid,
        "stage": state.stage,
        "profile": state.profile,
        "verify": state.verify or {},
        "report": state.report,
        "export": {"hint": "调用 /api/export 导出清洗结果"},
    }


app = create_app()
