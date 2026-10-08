# SPDX-License-Identifier: Apache-2.0
"""pytest 公共配置：注入仓库 backend 目录到 sys.path（使 `import app.xxx` 可用）。

- sys.path 注入 backend/ 根目录（代码位于 backend/app/）。
- 提供 client fixture：注入临时 SQLite 审计库，隔离测试与仓库 data/。
"""
import os
import sys

import pytest

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """独立 Runtime（临时审计库）+ TestClient，避免测试污染仓库 data/。"""
    import app.server.app as srv

    def _isolated_runtime():
        return srv.Runtime(str(tmp_path / "test-runs.db"))

    monkeypatch.setattr(srv, "_new_runtime", _isolated_runtime)
    from fastapi.testclient import TestClient

    # raise_server_exceptions=False：允许测试如实断言 5xx 响应（含 fail-loud 分支）
    return TestClient(srv.create_app(), raise_server_exceptions=False)
