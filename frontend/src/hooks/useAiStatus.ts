// SPDX-License-Identifier: Apache-2.0
/** 界面三态：AI 通道状态（通道级，与 thread 无关）。
 *
 *  三态口径：
 *  - 未启用（默认）→ `available=false`，调用方**不渲染任何 AI 入口**（不占版面）；
 *  - 正常 → `available=true`；
 *  - 失败 → 状态里带 `last_error`，由各区块显示原因 + 重试，**不阻塞其他功能**。
 *
 *  用组件内自取状态的方式，避免给 800+ 行的 useSession 增加 AI 耦合。
 */
import { useCallback, useEffect, useState } from "react";
import { AiStatusResult, api } from "../api";

export interface AiStatusState {
  /** 已启用且 provider 可用（= 允许渲染 AI 入口） */
  available: boolean;
  status: AiStatusResult | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useAiStatus(): AiStatusState {
  const [status, setStatus] = useState<AiStatusResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      /* probe=false：只读状态缓存，不在进屏时主动外呼。 */
      setStatus(await api.aiStatus("", false));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return {
    available: Boolean(status?.enabled && status?.provider === "openai_compatible"),
    status,
    loading,
    error,
    reload: () => void load(),
  };
}
