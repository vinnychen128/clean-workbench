// SPDX-License-Identifier: Apache-2.0
/** 设置 / 关于（通用要求落地）：本地声明、无云追踪、接口状态与版本信息。
 *
 *  「AI 辅助」分组：
 *  - 三态之一「未启用」在这里体现为「默认关」的如实展示（不含任何输入框）；
 *  - 配置唯一来源是仓库根 `.env`（密钥只从环境变量读），故本页**只读展示**已配置值，
 *    不提供密钥输入框、不回显密钥；
 *  - 「会发送什么」预览取后端 `/api/ai/status` 的 `preview`（与实际请求体同源）；
 *  - 「测试连接」才真探一次（`probe=true`），失败只显示原因 + 可重试，不阻塞其他功能。
 */
import React, { useCallback, useEffect, useState } from "react";
import { AiStatusResult, HealthResult, api } from "../api";
import { aiReasonText } from "../lib/ai";
import { Badge, Button, Collapse, Skeleton } from "./ui/primitives";

const SHARING_LABEL: Record<string, string> = {
  shape_only: "只发形态（列名 + 形态标签 + 列级统计，默认）",
  redacted_samples: "形态 + 脱敏采样值（需显式开启）",
};

export function SettingsPanel({ onClose, health, busy }: {
  onClose: () => void;
  health: HealthResult | null;
  busy: boolean;
}) {
  const [ai, setAi] = useState<AiStatusResult | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);

  /* 状态是「通道级」信息，与 thread 无关，故不传 thread_id（后端两参数均可省略）。 */
  const loadAiStatus = useCallback(async (probe: boolean) => {
    setAiBusy(true);
    setAiError(null);
    try {
      setAi(await api.aiStatus("", probe));
    } catch (e) {
      setAiError(e instanceof Error ? e.message : String(e));
    } finally {
      setAiBusy(false);
    }
  }, []);

  useEffect(() => {
    void loadAiStatus(false);
  }, [loadAiStatus]);

  const aiConfigured = Boolean(ai?.enabled && ai?.provider === "openai_compatible");
  const preview = ai?.preview;

  return (
    <div className="drawer" role="dialog" aria-modal="true" aria-label="设置与关于">
      <div className="drawer__backdrop" onClick={onClose} />
      <div className="drawer__panel drawer__panel--narrow">
        <div className="drawer__head">
          <h3 className="drawer__title">设置 / 关于</h3>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="关闭">×</button>
        </div>

        <div className="settings">
          <section className="settings__group">
            <h4>运行方式</h4>
            <ul className="settings__list">
              <li><Badge tone="success">本地</Badge> 全部处理在本机完成，数据不上传云端</li>
              <li><Badge tone="success">隐私</Badge> 无云端追踪、无遥测上报、无第三方统计</li>
              <li><Badge tone="neutral">离线</Badge> 浏览器本地存储仅用于运行历史（localStorage）</li>
            </ul>
          </section>

          <section className="settings__group">
            <h4>AI 辅助</h4>
            {aiBusy && !ai ? (
              <Skeleton h={96} />
            ) : aiError ? (
              <>
                <p className="muted">AI 状态读取失败：{aiError}</p>
                <Button size="sm" variant="secondary" onClick={() => void loadAiStatus(false)}>
                  重试
                </Button>
              </>
            ) : (
              <>
                <ul className="settings__list">
                  <li>
                    总开关（默认关）：
                    <Badge tone={aiConfigured ? "success" : "neutral"}>
                      {aiConfigured ? "已启用" : "关闭"}
                    </Badge>
                  </li>
                  <li>Provider：<code className="mono">{ai?.provider ?? "none"}</code></li>
                  <li>Base URL：<code className="mono">{ai?.base_url || "（未配置）"}</code></li>
                  <li>模型名：<code className="mono">{ai?.model || "（未配置）"}</code></li>
                  <li>
                    密钥状态：<Badge tone={ai?.key_configured ? "success" : "neutral"}>
                      {ai?.key_configured ? "已设置" : "未设置"}
                    </Badge>
                    <span className="muted">只读 · 来源：环境变量 CLEAN_AI_API_KEY</span>
                  </li>
                  <li>
                    数据共享级别：
                    <Badge tone={ai?.value_sharing === "shape_only" ? "success" : "warning"}>
                      {SHARING_LABEL[ai?.value_sharing ?? "shape_only"] ?? ai?.value_sharing}
                    </Badge>
                  </li>
                  <li>
                    列名对外：
                    <Badge tone={ai?.column_name_sharing === "masked" ? "success" : "neutral"}>
                      {ai?.column_name_sharing === "masked" ? "敏感列名已隐藏（列#n）" : "原样"}
                    </Badge>
                  </li>
                  <li>
                    连通性：
                    <Badge tone={ai?.reachable ? "success" : ai?.last_error ? "warning" : "neutral"}>
                      {ai?.reachable ? "可达" : "不可达"}
                    </Badge>
                    {/* 只拼原因短语，渲染为「不可达（端点不可达）」；此处不得再套「AI 暂时不可用」整句 */}
                    {!ai?.reachable && <span className="muted">（{aiReasonText(ai?.last_error)}）</span>}
                  </li>
                  {ai?.checked_at && (
                    <li>最近探测：<code className="mono">{ai.checked_at}</code></li>
                  )}
                </ul>

                {ai?.config_errors && ai.config_errors.length > 0 && (
                  <p className="muted">配置待补：{ai.config_errors.join("；")}</p>
                )}

                <p className="muted settings__meta">
                  开关与地址在仓库根 <code className="mono">.env</code> 填写（<code className="mono">CLEAN_AI_ENABLED</code> /
                  <code className="mono"> CLEAN_AI_PROVIDER</code> / <code className="mono">CLEAN_AI_BASE_URL</code> /
                  <code className="mono"> CLEAN_AI_MODEL</code>），改后重启本地服务生效；密钥只放在环境变量里，
                  本界面不提供输入框、不回显。
                </p>

                {preview && (
                  <Collapse title="会发送什么" meta="与实际请求体一致">
                    <ul className="settings__list">
                      <li>字段：<code className="mono">{preview.fields.join("、")}</code></li>
                      <li>样例：<code className="mono">{JSON.stringify(preview.example)}</code></li>
                      <li>永不发送：{preview.never_sent.join("、")}</li>
                      <li>密钥来源：{preview.key_source}</li>
                    </ul>
                  </Collapse>
                )}

                <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", marginTop: "var(--space-3)", flexWrap: "wrap" }}>
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={aiBusy}
                    disabled={!aiConfigured}
                    onClick={() => void loadAiStatus(true)}
                    title={aiConfigured ? "向已配置端点发一次健康探测" : "未启用时不会外呼"}
                  >
                    测试连接
                  </Button>
                  {!aiConfigured && <span className="muted">未启用时不会发起任何外呼。</span>}
                </div>
              </>
            )}
          </section>

          <section className="settings__group">
            <h4>服务状态</h4>
            {busy ? (
              <Skeleton h={56} />
            ) : health ? (
              <ul className="settings__list">
                <li>状态：<Badge tone={health.status === "ok" ? "success" : "danger"}>{health.status}</Badge></li>
                <li>版本：<code className="mono">{health.version ?? "-"}</code></li>
                <li>引擎：<code className="mono">{health.engine ?? "-"}</code></li>
                {health.detectors && (
                  <li>检测器：<code className="mono">{health.detectors.join(", ")}</code></li>
                )}
                {health.operations && (
                  <li>操作：<code className="mono">{health.operations.join(", ")}</code></li>
                )}
              </ul>
            ) : (
              <p className="muted">后端服务未连接。请在本地启动清洗服务后刷新页面。</p>
            )}
          </section>

          <section className="settings__group">
            <h4>关于</h4>
            <p className="settings__about">
              清洗工作台（CleanWorkbench）—— 面向本地数据的“精密工具”式数据清洗工作台：
              文件上传 → 数据体检 → 配方编排 → 人工确认门 → 执行 → 校验 → 报告 → 导出，
              全程数据不出本机。设计遵循冷中性底、单一强调色、模块化字阶与完整交互五态规范。
            </p>
            <p className="muted settings__meta">技术栈：React 18 · TypeScript · Vite · FastAPI 后端（127.0.0.1:8321）</p>
          </section>
        </div>
      </div>
    </div>
  );
}
