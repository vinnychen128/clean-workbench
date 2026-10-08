// SPDX-License-Identifier: Apache-2.0
/** 本地数据清洗台 · 主应用（向导流）
 *  七屏线性向导：上传 → 体检 → 配方 → 确认 → 执行 → 报告 → 导出。
 *  壳层与状态分离：AppShell 负责骨架，useSession 负责会话状态，screens/* 只做呈现与触发。
 *  设计：冷中性底 / 单一强调色 / 五态 / 骨架屏 / 空态引导（styles/tokens.css）。 */
import { useState } from "react";
import { AppShell } from "./components/AppShell";
import { HistoryEntry, HistoryPanel } from "./components/HistoryPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { useSession } from "./hooks/useSession";
import { EdaScreen } from "./screens/EdaScreen";
import { ExecuteScreen } from "./screens/ExecuteScreen";
import { ExportScreen } from "./screens/ExportScreen";
import { HitlScreen } from "./screens/HitlScreen";
import { RecipeScreen } from "./screens/RecipeScreen";
import { ReportScreen } from "./screens/ReportScreen";
import { UploadScreen } from "./screens/UploadScreen";

export default function App() {
  const s = useSession();
  const [drawer, setDrawer] = useState<null | "history" | "settings">(null);

  /* 历史记录仅存本机 localStorage；后端会话不跨进程保留，因此这里只做记录与提示。 */
  const handleHistoryLoad = (entry: HistoryEntry) => {
    setDrawer(null);
    s.setError("");
    s.setInfo(
      `历史会话 ${entry.thread_id}（${entry.file_name}）仅作记录：后端会话不跨重启保留，如需继续请重新上传该文件。`,
    );
    s.goTo("upload");
  };

  return (
    <>
      <AppShell s={s} onOpenHistory={() => setDrawer("history")} onOpenSettings={() => setDrawer("settings")}>
        {s.screen === "upload" && <UploadScreen s={s} />}
        {s.screen === "eda" && <EdaScreen s={s} />}
        {s.screen === "recipe" && <RecipeScreen s={s} />}
        {s.screen === "hitl" && <HitlScreen s={s} />}
        {s.screen === "execute" && <ExecuteScreen s={s} />}
        {s.screen === "report" && <ReportScreen s={s} />}
        {s.screen === "export" && <ExportScreen s={s} />}
      </AppShell>

      {drawer === "history" && <HistoryPanel onClose={() => setDrawer(null)} onLoad={handleHistoryLoad} />}
      {drawer === "settings" && (
        <SettingsPanel
          onClose={() => setDrawer(null)}
          health={s.health}
          busy={!s.health && !s.healthError}
        />
      )}
    </>
  );
}
