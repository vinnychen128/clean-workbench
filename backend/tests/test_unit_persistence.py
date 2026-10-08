# SPDX-License-Identifier: Apache-2.0
"""L1 单元测试：SQLite 执行记录与审计。

覆盖：线程增改查 / 配方落库 / 转换日志 / 导出记录 / 仅存元数据。
"""
import json

from app.persistence.store import Store


def test_store_roundtrip(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    try:
        store.start_thread("t1", {"file_name": "s.csv"})
        assert store.get_thread("t1")["source"] == {"file_name": "s.csv"}
        assert store.get_thread("t1")["status"] == "RUNNING"

        store.update_thread("t1", "PLANNED", {"schema_id": "clean-recipe/v1"})
        assert store.get_thread("t1")["status"] == "PLANNED"
        assert store.get_thread("t1")["recipe"]["schema_id"] == "clean-recipe/v1"
    finally:
        store.close()


def test_store_transform_log(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    try:
        store.start_thread("t1", {"file_name": "s.csv"})
        store.append_log("t1", 1, "row_dedupe", {"rows_affected": 2})
        row = store._conn.execute("SELECT * FROM transform_log WHERE thread_id='t1'").fetchone()
        assert row[2] == 1 and row[3] == "row_dedupe"
        assert json.loads(row[4])["rows_affected"] == 2
    finally:
        store.close()


def test_store_export_log(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    try:
        store.start_thread("t1", {"file_name": "s.csv"})
        store.append_export("t1", "csv", "/tmp/out.csv")
        row = store._conn.execute("SELECT * FROM export_log WHERE thread_id='t1'").fetchone()
        assert row[2] == "csv" and row[3] == "/tmp/out.csv"
    finally:
        store.close()


def test_store_list_threads(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    try:
        store.start_thread("t2", {"file_name": "b.csv"})
        store.start_thread("t1", {"file_name": "a.csv"})
        threads = store.list_threads()
        ids = [t["thread_id"] for t in threads]
        assert "t1" in ids and "t2" in ids
        assert all("file_name" in t["source"] for t in threads)
    finally:
        store.close()


def test_store_get_missing(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    try:
        assert store.get_thread("nope") is None
    finally:
        store.close()
