# 贡献指南

感谢你愿意参与。本项目遵循 Apache-2.0 许可证，欢迎提交 PR 与 issue。

## 行为准则

- 友善、专业；以事实和测试证据说话。
- **禁止在 issue / PR / 代码注释中粘贴客户真实数据**，一律用合成样例（`samples/`）复现。

## 环境

- Python 3.11+ / Node 18+
- 依赖版本以 `backend/requirements.txt` 与 `frontend/package.json` 锁定为准
- 许可证白名单：Apache-2.0 / MIT / BSD / ISC；**GPL / AGPL / SSPL 不得引入**

## 提交规范

1. 从 `main` 拉新分支：`git checkout -b feat/xxx`
2. 写代码 + 单测（检测器 / 操作类必须有纯函数单测）
3. 自测：`cd backend && python -m pytest`
4. 提交信息：`feat(scope): 一句话说明`，如 `feat(detectors): add unit detector`
5. 开 PR 描述改动、测试结果与影响范围

## 代码约定

- **确定性优先**：禁止引入随机数、外部 API、LLM 调用；同一输入 + 同一配方必须逐字节一致。
- **原件只读**：任何代码不得原地覆盖用户原文件；清洗产物 = 副本 + 转换日志。
- **失败可见（fail-loud）**：异常必须进入 `errors` 列表并最终出现在报告与执行表中，禁止静默吞错。
- **插件化**：新增检测器 / 操作继承统一基类并注册，不改动既有类。

## 发布前自查

- [ ] `git ls-files` 对账：无客户数据 / 无专有素材 / 无凭证 / 无本地绝对路径
- [ ] 依赖许可证兼容表已更新并落档（`docs/dependency-license.md`）
- [ ] 合成数据冒烟通过
- [ ] README 截图 / 快速上手可复现
