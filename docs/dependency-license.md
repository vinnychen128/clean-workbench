# 依赖许可证兼容表（全部版本已逐条核对 PyPI / npm 实际发布版本）

> 依据：本项目许可证核查口径⑧「第三方代码/依赖的许可证兼容核查」。白名单：Apache-2.0 / MIT / BSD 系 / ISC（含等价的宽松族 Zlib / CC0-1.0）；强 copyleft（GPL / AGPL / SSPL）不得混入，命中即替换或剔除。

## 后端（backend/requirements.txt）

| 依赖 | 版本 | 许可证 | 结论 |
|---|---|---|---|
| fastapi | 0.115.6 | MIT | ✅ 兼容 |
| uvicorn | 0.32.1 | BSD-3-Clause | ✅ 兼容 |
| pydantic | 2.10.4 | MIT | ✅ 兼容 |
| python-multipart | 0.0.20 | Apache-2.0 | ✅ 兼容 |
| pandas | 2.2.3 | BSD-3-Clause | ✅ 兼容 |
| python-dateutil | 2.9.0.post0 | BSD-3-Clause（/Apache-2.0 双许可，按 BSD-3-Clause 用） | ✅ 兼容（**直接依赖**：`cell_ops.CellDateNormalizeOp` 直接 `from dateutil import parser`；此前仅由 pandas 传递引入，属隐式依赖，已显式 pin） |
| openpyxl | 3.1.5 | MIT | ✅ 兼容 |
| xlrd | 2.0.1 | BSD-3-Clause | ✅ 兼容 |
| pypdf | 6.18.1 | BSD-3-Clause | ✅ 兼容（PDF 文本层直读 + 扫描件判定） |
| langgraph | 0.2.60 | MIT | ✅ 兼容 |
| langgraph-checkpoint | 2.1.2 | MIT | ✅ 兼容（检查点接口，SqliteSaver 依赖） |
| langgraph-checkpoint-sqlite | 2.0.11 | MIT | ✅ 兼容（跨会话检查点持久化） |
| odfpy | 1.4.1 | Apache-2.0 / GPL / LGPL 多许可并存 | ✅ 兼容（本项目按 Apache-2.0 条款使用；**版本修正**：原钉 1.4.2 在 PyPI 不存在，已改为实际最新 1.4.1；如发行需排除 GPL 分支可评估替换） |
| xlwt | 1.3.0 | BSD-3-Clause | ✅ 兼容（xls 往返测试依赖） |
| reportlab | 4.2.5 | BSD-3-Clause | ✅ 兼容 |
| python-dotenv | 1.0.1 | BSD-3-Clause | ✅ 兼容 |
| pytest | 8.3.4 | MIT | ✅ 兼容（**不升 9.0.3**：`pytest-asyncio==0.25.2` 元数据硬约束 `pytest<9,>=8.2`，`pip install --dry-run pytest==9.0.3 pytest-asyncio==0.25.2` 实测 `ResolutionImpossible`。接受 CVE-2025-71176 / GHSA-6w46-j5rx-g56g，仅影响开发期测试工具） |
| pytest-asyncio | 0.25.2 | Apache-2.0 | ✅ 兼容 |
| httpx | 0.28.1 | BSD-3-Clause | ✅ 兼容（**运行时直接依赖**：AI 辅助层以 httpx 走 OpenAI 兼容协议调用 AI 通道，见 `backend/app/ai/client.py`；此前仅由测试区 `fastapi.testclient` 传递引入，属隐式依赖。同时仍是 TestClient 依赖；**不引入任何 LLM 专用 SDK**） |

## 前端（frontend/package.json）

| 依赖 | 版本 | 许可证 | 结论 |
|---|---|---|---|
| react | 18.3.1 | MIT | ✅ 兼容 |
| react-dom | 18.3.1 | MIT | ✅ 兼容 |
| typescript | 5.7.2 | Apache-2.0 | ✅ 兼容 |
| vite | 5.4.11 | MIT | ✅ 兼容 |
| @vitejs/plugin-react | 4.3.4 | MIT | ✅ 兼容 |
| @types/react | 18.3.14 | MIT | ✅ 兼容 |
| @types/react-dom | 18.3.2 | MIT | ✅ 兼容 |

## 传递依赖与全树复算（2026-09-18 补：传递依赖覆盖度）

**口径**（两条命令可原地复跑；**未锁版的解析闭包会随 PyPI 索引变动**，故本节数值是 **2026-09-18 快照**，逐包数值以本节末「复算时间」为准 —— 例：同日复核 `numpy` 可能解析到 2.5.3 而非下表所记 2.4.6，其许可证表达式不变）

- npm 树：`frontend/package-lock.json` 的**全部** `packages` 条目（含 dev、含传递依赖；排除根条目 `""`），取每包 `license` 字段 → **114 条**。
- Python 树：`pip install --dry-run --ignore-installed --report - -r backend/requirements.txt` 的**解析闭包**（直接 + 传递，版本现解析）→ **64 包**（`requirements.txt` 声明 20 项，其中 `chardet` / `pillow` 为**显式登记的传递依赖**；另 44 项为解析引入的传递依赖）。
- 许可证取值优先级：PyPI `info.license_expression` > `info.license` > `License::` classifier > 本地 `dist-info` METADATA（仅 PyPI 未标注时回退本地）。
- 判定口径：「白名单内」= 解析出的许可证族**全部**落在白名单枚举 = `Apache-2.0` / `MIT` / `BSD` 系（含 `0BSD` / `BSD-2-Clause` / `BSD-3-Clause` / `Modified BSD`）/ `ISC` / `Zlib` / `CC0-1.0`；出现任一**登记触发族**（`MPL` / `PSFL`·`PSF` / `CC-BY` / `LGPL` / `GPL` / `AGPL` / `SSPL` / 未标注）即**登记**，多许可表达式照列、不挑宽松分支。**登记 ≠ 不可用**：登记项一律在表内给出处置结论（多为「宽松但非白名单枚举族，登记说明后可用」，或「弱 copyleft，未改源码即无义务」）。
- 族名解析：族名匹配为大小写无关的**子串**匹配（故 `MIT-CMU` → MIT 族、`0BSD` → BSD 族、`PSF-2.0` → PSF 族）；元数据只给标签式取值（如 `Dual License`）时，按其 `License::` classifiers 解析；两级都无可解析族名，才按「未标注」登记。表达式里出现白名单枚举外的族名时，**必须在本节内显式列出并说明等价性**（本例：`numpy` 的 `Zlib` / `CC0-1.0`，逐条说明见下方 Python 闭包清单之后的两条），不默认放行。
- 类型列口径（Python 闭包表）：`直接` = 后端表所列 **18 项**直接依赖；`传递` = 其余 46 项 —— 其中 `chardet` / `pillow` 虽写进 `backend/requirements.txt`（为锁定许可证区间与下限），角色仍是 `reportlab` 的传递依赖，故按传递计。
- 证据链接（现取）：Python 每包 `https://pypi.org/pypi/<包>/<版本>/json`；npm 每包 `https://registry.npmjs.org/<包>/<版本>`。

**复算结果**

| 树 | 条目数 | 许可证分布（按条目计；多许可表达式**只归入一个桶** —— 白名单族优先，同类内按固定族序取先命中者，故各桶之和 = 条目数） |
|---|---|---|
| npm（`package-lock.json` 全量，含 dev） | 114 | MIT 105 · ISC 5 · Apache-2.0 2 · CC-BY 1 · BSD 1 |
| Python（`requirements.txt` 解析闭包） | 64 | MIT 30 · BSD 23 · Apache-2.0 8 · PSFL 2 · MPL 1 |

*两处易被读成「漏登记」的条目，按上述口径逐条说明：*
- `numpy`（表达式 `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`）：五个族**全部落在白名单枚举内**（`0BSD` 属 BSD 系，`Zlib` / `CC0-1.0` 为等价宽松族），故判白名单内、不登记。
- `python-dateutil`（PyPI `info.license` = 标签式 `Dual License`，本身无族名）：按其 classifiers 解析为 `Apache Software License` + `BSD License` 两族，均在白名单枚举内。**已从传递依赖升为直接依赖**，故在「后端」表内单独登记一行（版本 `2.9.0.post0`）。

- 强 copyleft（GPL / AGPL / SSPL / LGPL）**单独出现**（无可选宽松分支）：**npm 0 命中 / Python 0 命中**。
- 元数据里出现 GPL / LGPL 字样的条目：Python **1 项**（`odfpy`：PyPI classifiers 同时列 Apache Software License / GPL / LGPL，本项目按 **Apache-2.0** 条款使用，见「后端」表）。
- 需登记项（出现白名单外的族）：npm **1 项** + Python **5 项**，逐条见下表。

**需登记项（逐条登记 + 证据）**

| 包 | 版本 | 许可证（现取） | 树 | 归属 | 处置结论 |
|---|---|---|---|---|---|
| `caniuse-lite` | 1.0.30001810 | CC-BY-4.0 | npm | dev（构建期，非运行时），直接依赖 | CC-BY-4.0 仅署名义务，不参与运行时逻辑；如需替换可评估 `browserslist`（MIT） |
| `certifi` | 2026.7.22 | MPL-2.0 | Python | 传递依赖（由 httpcore / httpx / requests 引入） | MPL-2.0 为**弱 copyleft（文件级）**：本项目未修改其源码、以依赖方式调用，不触发源码开放义务；且仅充当 TLS 根证书容器 |
| `defusedxml` | 0.7.1 | PSFL | Python | 传递依赖（由 odfpy / pillow 引入） | PSFL / PSF 系许可证为宽松许可（等价 BSD 系），无 copyleft 义务 |
| `odfpy` | 1.4.1 | Apache Software License | Python | 直接依赖 | PyPI 元数据里 Apache-2.0 / GPL / LGPL **多许可并存**（本项目按 Apache-2.0 条款使用），非「单独强 copyleft」 |
| `orjson` | 3.12.0 | MPL-2.0 AND (Apache-2.0 OR MIT) | Python | 传递依赖（由 fastapi / langgraph-sdk / langsmith 引入） | MPL-2.0 为**弱 copyleft（文件级）**：本项目未修改其源码、以依赖方式调用，不触发源码开放义务 |
| `typing_extensions` | 4.16.0 | PSF-2.0 | Python | 传递依赖（由 anyio / fastapi / httpx2 / langchain-core / langsmith / pydantic / pydantic_core / pypdf / starlette / uvicorn 引入） | PSFL / PSF 系许可证为宽松许可（等价 BSD 系），无 copyleft 义务 |

*证据（现取，逐条可复取）：*
- `caniuse-lite` npm：https://registry.npmjs.org/caniuse-lite/1.0.30001810
- `certifi` PyPI：https://pypi.org/pypi/certifi/2026.7.22/json
- `defusedxml` PyPI：https://pypi.org/pypi/defusedxml/0.7.1/json
- `odfpy` PyPI：https://pypi.org/pypi/odfpy/1.4.1/json
- `orjson` PyPI：https://pypi.org/pypi/orjson/3.12.0/json
- `typing_extensions` PyPI：https://pypi.org/pypi/typing_extensions/4.16.0/json

**Python 闭包清单（64 包，逐包取值）**

| 包 | 版本 | 许可证（现取） | 取值来源 | 类型 | 判定 |
|---|---|---|---|---|---|
| `aiosqlite` | 0.22.1 | MIT License | pypi:classifier | 传递 | ✅ 白名单内 |
| `annotated-types` | 0.8.0 | MIT | pypi:license_expression | 传递 | ✅ 白名单内 |
| `anyio` | 4.15.1 | MIT | pypi:license_expression | 传递 | ✅ 白名单内 |
| `certifi` | 2026.7.22 | MPL-2.0 | pypi:license | 传递 | ⚠️ 需登记 |
| `chardet` | 7.6.0 | 0BSD | pypi:license_expression | 传递 | ✅ 白名单内 |
| `charset-normalizer` | 3.5.1 | MIT | pypi:license | 传递 | ✅ 白名单内 |
| `click` | 8.5.0 | BSD-3-Clause | pypi:license_expression | 传递 | ✅ 白名单内 |
| `defusedxml` | 0.7.1 | PSFL | pypi:license | 传递 | ⚠️ 需登记 |
| `distro` | 1.9.0 | Apache License, Version 2.0 | pypi:license | 传递 | ✅ 白名单内 |
| `et_xmlfile` | 2.0.0 | MIT | pypi:license | 传递 | ✅ 白名单内 |
| `fastapi` | 0.115.6 | MIT License | pypi:classifier | 直接 | ✅ 白名单内 |
| `h11` | 0.16.0 | MIT | pypi:license | 传递 | ✅ 白名单内 |
| `httpcore` | 1.0.9 | BSD-3-Clause | pypi:license_expression | 传递 | ✅ 白名单内 |
| `httpcore2` | 2.13.0 | BSD-3-Clause | pypi:license_expression | 传递 | ✅ 白名单内 |
| `httpx` | 0.28.1 | BSD-3-Clause | pypi:license | 直接 | ✅ 白名单内 |
| `httpx2` | 2.13.0 | BSD-3-Clause | pypi:license_expression | 传递 | ✅ 白名单内 |
| `idna` | 3.20 | BSD-3-Clause | pypi:license_expression | 传递 | ✅ 白名单内 |
| `iniconfig` | 2.3.0 | MIT | pypi:license_expression | 传递 | ✅ 白名单内 |
| `jsonpatch` | 1.33 | Modified BSD License | pypi:license | 传递 | ✅ 白名单内 |
| `jsonpointer` | 3.1.1 | Modified BSD License | pypi:license | 传递 | ✅ 白名单内 |
| `langchain-core` | 0.3.86 | MIT | pypi:license | 传递 | ✅ 白名单内 |
| `langgraph` | 0.2.60 | MIT | pypi:license | 直接 | ✅ 白名单内 |
| `langgraph-checkpoint` | 2.1.2 | MIT | pypi:license_expression | 直接 | ✅ 白名单内 |
| `langgraph-checkpoint-sqlite` | 2.0.11 | MIT | pypi:license_expression | 直接 | ✅ 白名单内 |
| `langgraph-sdk` | 0.1.74 | MIT | pypi:license_expression | 传递 | ✅ 白名单内 |
| `langsmith` | 0.12.6 | MIT | pypi:license | 传递 | ✅ 白名单内 |
| `numpy` | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | pypi:license_expression | 传递 | ✅ 白名单内 |
| `odfpy` | 1.4.1 | Apache Software License | pypi:classifier | 直接 | ⚠️ 需登记(多许可, 按宽松分支使用) |
| `openpyxl` | 3.1.5 | MIT | pypi:license | 直接 | ✅ 白名单内 |
| `orjson` | 3.12.0 | MPL-2.0 AND (Apache-2.0 OR MIT) | pypi:license_expression | 传递 | ⚠️ 需登记(多许可, 按宽松分支使用) |
| `ormsgpack` | 1.12.2 | Apache-2.0 OR MIT | pypi:license_expression | 传递 | ✅ 白名单内 |
| `packaging` | 25.0 | Apache Software License | pypi:classifier | 传递 | ✅ 白名单内 |
| `pandas` | 2.2.3 | BSD License | pypi:classifier | 直接 | ✅ 白名单内 |
| `pillow` | 12.3.0 | MIT-CMU | pypi:license_expression | 传递 | ✅ 白名单内 |
| `pluggy` | 1.6.0 | MIT | pypi:license | 传递 | ✅ 白名单内 |
| `pydantic` | 2.10.4 | MIT License | pypi:classifier | 直接 | ✅ 白名单内 |
| `pydantic_core` | 2.27.2 | MIT | pypi:license | 传递 | ✅ 白名单内 |
| `pypdf` | 6.18.1 | BSD-3-Clause | pypi:license_expression | 直接 | ✅ 白名单内 |
| `pytest` | 8.3.4 | MIT | pypi:license | 直接 | ✅ 白名单内 |
| `pytest-asyncio` | 0.25.2 | Apache 2.0 | pypi:license | 直接 | ✅ 白名单内 |
| `python-dateutil` | 2.9.0.post0 | Dual License | pypi:license | 传递 | ✅ 白名单内 |
| `python-dotenv` | 1.0.1 | BSD-3-Clause | pypi:license | 直接 | ✅ 白名单内 |
| `python-multipart` | 0.0.20 | Apache Software License | pypi:classifier | 直接 | ✅ 白名单内 |
| `pytz` | 2026.3.post1 | MIT | pypi:license | 传递 | ✅ 白名单内 |
| `PyYAML` | 6.0.3 | MIT | pypi:license | 传递 | ✅ 白名单内 |
| `reportlab` | 4.2.5 | BSD License | pypi:classifier | 直接 | ✅ 白名单内 |
| `requests` | 2.34.2 | Apache-2.0 | pypi:license | 传递 | ✅ 白名单内 |
| `requests-toolbelt` | 1.0.0 | Apache 2.0 | pypi:license | 传递 | ✅ 白名单内 |
| `six` | 1.17.0 | MIT | pypi:license | 传递 | ✅ 白名单内 |
| `sniffio` | 1.3.1 | MIT OR Apache-2.0 | pypi:license | 传递 | ✅ 白名单内 |
| `sqlite-vec` | 0.1.9 | MIT License, Apache License, Version 2.0 | pypi:license | 传递 | ✅ 白名单内 |
| `starlette` | 0.41.3 | BSD-3-Clause | pypi:license | 传递 | ✅ 白名单内 |
| `tenacity` | 9.1.4 | Apache 2.0 | pypi:license | 传递 | ✅ 白名单内 |
| `truststore` | 0.10.4 | MIT | pypi:license_expression | 传递 | ✅ 白名单内 |
| `typing_extensions` | 4.16.0 | PSF-2.0 | pypi:license_expression | 传递 | ⚠️ 需登记 |
| `tzdata` | 2026.4 | Apache-2.0 | pypi:license | 传递 | ✅ 白名单内 |
| `urllib3` | 2.8.0 | MIT | pypi:license_expression | 传递 | ✅ 白名单内 |
| `uuid_utils` | 0.17.1 | BSD-3-Clause | pypi:license_expression | 传递 | ✅ 白名单内 |
| `uvicorn` | 0.32.1 | BSD-3-Clause | pypi:license | 直接 | ✅ 白名单内 |
| `websockets` | 17.1 | BSD-3-Clause | pypi:license_expression | 传递 | ✅ 白名单内 |
| `xlrd` | 2.0.1 | BSD | pypi:license | 直接 | ✅ 白名单内 |
| `xlwt` | 1.3.0 | BSD | pypi:license | 直接 | ✅ 白名单内 |
| `xxhash` | 4.0.1 | BSD-2-Clause | pypi:license | 传递 | ✅ 白名单内 |
| `zstandard` | 0.25.0 | BSD-3-Clause | pypi:license_expression | 传递 | ✅ 白名单内 |

*逐包证据路径 = `https://pypi.org/pypi/<包>/<版本>/json`（上表每行据此可复取）。*

**外部对照（核实两条断言）**

- `chardet`：**7.6.0 = 0BSD**（https://pypi.org/pypi/chardet/7.6.0/json） vs **5.2.0 = LGPL**（https://pypi.org/pypi/chardet/5.2.0/json） → 故 `backend/requirements.txt` 锁 `chardet>=7.0.0,<8`，任何解析器都不会落到 LGPL 区间。
- `caniuse-lite` 1.0.30001810 = **CC-BY-4.0**（https://registry.npmjs.org/caniuse-lite/1.0.30001810），npm 官方 registry 现取；`package-lock.json` 中标记 `dev: true`，仅 vite 构建期使用。

*本节数据复算时间：2026-09-18 22:38:26（复算脚本现取，未人工填写；脚本与原始报告不入库，数值可按本节两条命令复取；快照口径见节首）。*

## httpx 运行时直接依赖说明

- **依赖定位**：`httpx`（`0.28.1`）为 AI 辅助层的**运行时直接依赖** —— 以 httpx 走 OpenAI 兼容 HTTP 协议调用本地 / 云端点（`backend/app/ai/client.py`：`httpx.Client` 探活与 `complete()` 调用），属**运行时调用路径**；缺失时通道一律视为不可用（`no_httpx` → `reachable=false` / `degraded=true`），不影响主链路。同时仍是 `TestClient` 的依赖。
- **许可证结论**：**BSD-3-Clause**，落在白名单（Apache-2.0 / MIT / BSD 系 / ISC，含等价宽松族）内，无 copyleft 义务；与传递树中的 `httpcore`（BSD-3-Clause）/ `certifi`（MPL-2.0，已在「白名单之外」逐条登记）/ `idna`（BSD-3-Clause）/ `sniffio`（MIT OR Apache-2.0）组合一致，**未新增任何白名单之外条目**（白名单之外共 6 项，逐条登记见上）。
- **选型约束**：AI 通道只用 httpx 组装 OpenAI 兼容请求，**不引入任何 LLM 专用 SDK**（避免重依赖与许可证风险）；「只用 httpx + 不引 LLM SDK」是与 `requirements.txt` 同源的口径，升版任何依赖后须重新核对本表。
- **密钥纪律**：AI 通道密钥只从环境变量 `CLEAN_AI_API_KEY`（或仓库根 `.env`，权限 0600）读取，不入仓、不落日志、不落台账、不回显；`/api/ai/*` 四个端点一律不接收密钥字段（收到即 400）。
- **同步项**：与 `backend/requirements.txt` 同源核对（依赖升版后须重新核对本表）；本表为许可证侧的落点。

---

## 结论

- 全部**直接依赖**的许可证族落在白名单（口径见「传递依赖与全树复算」节）内，或为「宽松 + GPL / LGPL 多许可并存、本项目按宽松条款使用」（`odfpy`）；**无单独出现的** GPL / AGPL / SSPL / LGPL 强 copyleft。
- ✅ 已排除项：`PyMuPDF`（fitz）为 AGPL-3.0，命中强 copyleft 禁用条款，**不纳入依赖**；PDF 解析改用 `pypdf`（BSD-3-Clause），扫描件拒识分支同样以 pypdf 构造/探测，测试无需 AGPL 依赖。
- ⚠️ 关注项：`odfpy` 的 PyPI classifiers 同时列 Apache Software License / GPL / LGPL（多许可并存），本项目明确按 **Apache-2.0** 条款使用；若未来发布遇到法务疑义，可评估替换为纯宽松许可的 ODS 方案（列入待办）。
- 锁版口径：后端 `requirements.txt` **直接依赖**全部 `==` 精确锁定；**传递依赖**已显式登记 —— `chardet>=7.0.0,<8`（chardet ≤6.x 为 LGPL-2.1，本下限保证任何解析器都不会落到 LGPL 区间）、`pillow>=9.0.0`（reportlab 要求）；前端 `package.json` 全部精确版本 + `package-lock.json` 锁定传递依赖。
- 传递依赖覆盖度（2026-09-18 复算）：npm **114 条** + Python **64 包**（`requirements.txt` 声明 20 项 + 解析引入 44 项）—— **全树逐包取值**，分布与逐包证据见上一节（口径：`package-lock.json` 全量 + `pip --dry-run` 解析闭包；两条命令可原地复跑，版本为 2026-09-18 快照）。
- 强 copyleft（GPL / AGPL / SSPL）检索：**npm 0 命中 / Python 0 命中**；唯一与 GPL 相关的条目 `odfpy` 为 **Apache-2.0 / GPL / LGPL 多许可并存**（PyPI classifiers 三族同列），本项目按 Apache-2.0 条款使用。
- 白名单之外共 **6 项**（白名单口径见上：`Zlib` / `CC0-1.0` 这类等价宽松族已计入白名单，不计入本项），均已逐条登记：`certifi` = MPL-2.0、`defusedxml` = PSFL、`odfpy` = Apache Software License、`orjson` = MPL-2.0 AND (Apache-2.0 OR MIT)、`typing_extensions` = PSF-2.0、`caniuse-lite` = CC-BY-4.0（构建期，署名义务）。其中 `certifi` 的 MPL-2.0 为**弱 copyleft（文件级）**：不改其源码即无额外义务，故登记而不替换。
- `chardet` 事实核验（现取）：7.6.0 = 0BSD vs 5.2.0 = LGPL（证据：https://pypi.org/pypi/chardet/7.6.0/json 、https://pypi.org/pypi/chardet/5.2.0/json），故对 `chardet` 设下限 + 上界而非仅锁单版本。
- `httpx`：为**运行时直接依赖**，版本 `0.28.1`、许可证 BSD-3-Clause，落在白名单内，不触发替换评估；「不引入任何 LLM 专用 SDK」的选型约束见上节「httpx 运行时直接依赖说明」。
- 升版任何依赖后必须重新核对本表。
- 版本真实性核验：`pip index versions <pkg>` 逐条核对后端 **20 项声明**（= 后端表 18 项直接依赖 + `chardet` / `pillow` 2 项显式登记的传递依赖）、`npm view <pkg>@<ver> version` 逐条核对前端 7 项，**全部命中真实发布版本**；原 `odfpy==1.4.2`（不存在）已修正为 `1.4.1`，并补齐测试所需 `xlwt==1.3.0`。
- Python 版本要求：**≥ 3.10**（在 CPython 3.11.9 全新虚拟环境从零 `pip install -r backend/requirements.txt` 实测安装成功并全量跑测）。
