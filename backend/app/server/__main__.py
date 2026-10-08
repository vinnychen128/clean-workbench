"""本地服务启动入口：python -m app.server（仅绑定 127.0.0.1）。"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.server.app:app", host="127.0.0.1", port=8321, reload=False)
