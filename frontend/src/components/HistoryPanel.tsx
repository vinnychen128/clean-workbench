// SPDX-License-Identifier: Apache-2.0
/** 运行历史：最近解析会话（localStorage 本地记录），可查看节点进度与会话摘要。 */
import React, { useEffect, useState } from "react";
import { RunStatusNode, api } from "../api";
import { Badge, Button, EmptyState, Skeleton } from "./ui/primitives";

export interface HistoryEntry {
  thread_id: string;
  file_name: string;
  row_count: number;
  col_count: number;
  created_at: string;
  completed?: boolean;
}

export const HISTORY_KEY = "cleanworkbench.history.v1";

export function loadHistory(): HistoryEntry[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    return raw ? (JSON.parse(raw) as HistoryEntry[]) : [];
  } catch {
    return [];
  }
}

export function appendHistory(entry: HistoryEntry) {
  const next = [entry, ...loadHistory().filter((h) => h.thread_id !== entry.thread_id)].slice(0, 20);
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
  } catch {
    /* 存储满时忽略 */
  }
}

export function HistoryPanel({ onClose, onLoad }: {
  onClose: () => void;
  onLoad: (entry: HistoryEntry) => void;
}) {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [detail, setDetail] = useState<HistoryEntry | null>(null);
  const [nodes, setNodes] = useState<RunStatusNode[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    setEntries(loadHistory());
  }, []);

  const showDetail = async (e: HistoryEntry) => {
    setDetail(e);
    setNodes(null);
    setErr("");
    setBusy(true);
    try {
      // 尝试用 run_id 查询节点进度；thread 本身无 run 时回退为阶段推断
      const status = await api.runStatus(e.thread_id);
      if (status?.ok) {
        setNodes(status.nodes);
      } else {
        setNodes([
          { node_name: "parse", attempt: 1, status: "COMPLETED", started_at: e.created_at, ended_at: e.created_at },
          { node_name: "eda", attempt: 1, status: "COMPLETED", started_at: e.created_at, ended_at: e.created_at },
          { node_name: "report_build", attempt: 1, status: e.completed ? "COMPLETED" : "PENDING", started_at: null, ended_at: null },
        ]);
      }
    } catch {
      setNodes([
        { node_name: "parse", attempt: 1, status: "COMPLETED", started_at: e.created_at, ended_at: e.created_at },
        { node_name: "eda", attempt: 1, status: "COMPLETED", started_at: e.created_at, ended_at: e.created_at },
      ]);
      setErr("后端会话已过期：节点明细不可用，可重新上传文件继续。");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="drawer" role="dialog" aria-modal="true" aria-label="运行历史">
      <div className="drawer__backdrop" onClick={onClose} />
      <div className="drawer__panel">
        <div className="drawer__head">
          <h3 className="drawer__title">运行历史</h3>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="关闭">×</button>
        </div>

        {entries.length === 0 ? (
          <EmptyState
            icon="◷"
            title="暂无运行历史"
            desc="本机记录仅保存在浏览器 localStorage 中，不向任何外部服务同步。"
          />
        ) : (
          <ul className="history-list">
            {entries.map((e) => (
              <li key={e.thread_id}>
                <button type="button" className={`history-item${detail?.thread_id === e.thread_id ? " is-active" : ""}`} onClick={() => showDetail(e)}>
                  <span className="history-item__name">{e.file_name}</span>
                  <span className="history-item__meta">
                    {e.row_count} 行 × {e.col_count} 列 · {e.created_at}
                  </span>
                  <Badge tone={e.completed ? "success" : "neutral"}>{e.completed ? "已完成" : "未完成"}</Badge>
                </button>
              </li>
            ))}
          </ul>
        )}

        {detail && (
          <div className="history-detail">
            <div className="history-detail__head">
              <span className="muted">会话</span>
              <code className="mono">{detail.thread_id}</code>
              <Button size="sm" variant="primary" onClick={() => onLoad(detail)}>加载到工作台</Button>
            </div>
            {busy ? (
              <Skeleton h={60} />
            ) : (
              nodes && (
                <ol className="flow flow--compact">
                  {nodes.map((n, i) => (
                    <li key={i} className={`flow__item flow__item--${n.status === "COMPLETED" ? "done" : n.status === "FAILED" ? "failed" : n.status === "RUNNING" ? "running" : "pending"}`}>
                      <div className="flow__rail"><span className="flow__dot">{n.status === "COMPLETED" ? "✓" : n.status === "FAILED" ? "×" : i + 1}</span></div>
                      <div className="flow__body">
                        <span className="flow__label">{n.node_name}</span>
                        <span className="flow__time muted">{n.status}{n.attempt > 1 ? `（重试 ${n.attempt}）` : ""}</span>
                      </div>
                    </li>
                  ))}
                </ol>
              )
            )}
            {err && <div className="banner banner--info"><span className="banner__icon">i</span><span className="banner__text">{err}</span></div>}
          </div>
        )}
      </div>
    </div>
  );
}
