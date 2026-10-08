"""执行记录与审计：SQLite 本地持久化。

仅存元数据与引用（thread / 转换日志 / 导出记录），**绝不存储数据内容**（数据不出本机）。
线程安全：check_same_thread=False + 互斥锁串行化（FastAPI 线程池共享连接）。
"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    thread_id TEXT PRIMARY KEY,
    source_json TEXT NOT NULL,
    recipe_json TEXT,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS transform_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL,
    step INTEGER NOT NULL,
    op TEXT NOT NULL,
    log_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS export_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL,
    format TEXT NOT NULL,
    path TEXT NOT NULL,
    exported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS node_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL,
    node_name TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    error TEXT
);
"""


class Store:
    """本地 SQLite 存储。DB 文件位于仓库 data/clean-runs.db（不入版本库）。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        # check_same_thread=False：FastAPI 线程池多线程共享连接，配合锁串行化
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def start_thread(self, thread_id: str, source: Dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO threads (thread_id, source_json, status, started_at) VALUES (?,?,?,?)",
                (thread_id, json.dumps(source, ensure_ascii=False), "RUNNING", _now()),
            )
            self._conn.commit()

    def update_thread(self, thread_id: str, status: str, recipe: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            if recipe is not None:
                self._conn.execute(
                    "UPDATE threads SET status=?, recipe_json=?, finished_at=? WHERE thread_id=?",
                    (status, json.dumps(recipe, ensure_ascii=False), _now(), thread_id),
                )
            else:
                self._conn.execute("UPDATE threads SET status=?, finished_at=? WHERE thread_id=?",
                                   (status, _now(), thread_id))
            self._conn.commit()

    def append_log(self, thread_id: str, step: int, op: str, log: Dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO transform_log (thread_id, step, op, log_json) VALUES (?,?,?,?)",
                (thread_id, step, op, json.dumps(log, ensure_ascii=False)),
            )
            self._conn.commit()

    def append_export(self, thread_id: str, fmt: str, path: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO export_log (thread_id, format, path, exported_at) VALUES (?,?,?,?)",
                (thread_id, fmt, path, _now()),
            )
            self._conn.commit()

    def append_node_run(self, thread_id: str, node_name: str, status: str,
                        started_at: Optional[str] = None, ended_at: Optional[str] = None,
                        error: Optional[str] = None) -> int:
        """记录一次节点执行。attempt 为同节点累计执行次数（含校验回退重跑）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(attempt), 0) FROM node_runs WHERE thread_id=? AND node_name=?",
                (thread_id, node_name)).fetchone()
            attempt = int(row[0]) + 1
            self._conn.execute(
                "INSERT INTO node_runs (thread_id, node_name, attempt, status, started_at, ended_at, error)"
                " VALUES (?,?,?,?,?,?,?)",
                (thread_id, node_name, attempt, status, started_at, ended_at, error))
            self._conn.commit()
        return attempt

    def list_node_runs(self, thread_id: str) -> List[Dict[str, Any]]:
        """节点执行记录（每节点取最新一次 attempt），供 /api/run/{run_id} 与前端进度展示。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT node_name, attempt, status, started_at, ended_at FROM node_runs"
                " WHERE thread_id=? ORDER BY id ASC", (thread_id,)).fetchall()
        latest: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            latest[r[0]] = {"node_name": r[0], "attempt": r[1], "status": r[2],
                            "started_at": r[3], "ended_at": r[4]}
        return list(latest.values())

    def get_thread(self, thread_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM threads WHERE thread_id=?", (thread_id,)).fetchone()
        if not row:
            return None
        return {
            "thread_id": row[0],
            "source": json.loads(row[1]),
            "recipe": json.loads(row[2]) if row[2] else None,
            "status": row[3],
            "started_at": row[4],
            "finished_at": row[5],
        }

    def list_threads(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM threads ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        return [{
            "thread_id": r[0],
            "source": json.loads(r[1]),
            "status": r[3],
            "started_at": r[4],
            "finished_at": r[5],
        } for r in rows]


def _now() -> str:
    now = datetime.now()
    return f"{now.year}-{now.month:02d}-{now.day:02d} {now.hour:02d}:{now.minute:02d}:{now.second:02d}"
