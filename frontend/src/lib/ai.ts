// SPDX-License-Identifier: Apache-2.0
/** AI 失败原因码 → 人话（三处界面共用，口径一致）。
 *
 *  口径约定：本表**只写原因短语**，禁止自带「AI 暂时不可用」整句前缀——
 *  - 折叠区整句（AiReportSummary / AiColumnAdvice）由 `aiUnavailableText()` 统一组装一次前缀；
 *  - 设置面板连通性行直接取原因短语，与前置状态词拼成「不可达（端点不可达）」。
 *  若此处回填整句，会被调用方再套一层括号，形成「X（Y（Z））」式同类嵌套。
 *
 *  只做「如实说明不可用」，不含任何技术细节堆砌；重试入口由各区块自行提供。
 */
export const AI_REASON_LABEL: Record<string, string> = {
  disabled: "未启用（默认关）",
  unreachable: "端点不可达",
  timeout: "请求超时",
  bad_schema: "输出不合规，已降级",
  status_error: "状态查询失败",
};

/** 后端 reason 形如 `unreachable: ...`；取冒号前的原因码。 */
function reasonKey(reason?: string | null): string {
  return reason ? String(reason).split(":")[0].trim() : "";
}

/** 原因短语：只回**不带前缀**的人话短语（如「端点不可达」），由调用方按自身上下文组合。
 *
 *  设置面板连通性行用它拼成「不可达（端点不可达）」；无 reason 给「—」，未知码给 `fallback`。
 */
export function aiReasonText(reason?: string | null, fallback = "AI 暂时不可用"): string {
  if (!reason) return "—";
  return AI_REASON_LABEL[reasonKey(reason)] ?? fallback;
}

/** 失败态整句「AI 暂时不可用（端点不可达）」。
 *
 *  前缀只在这里出现一次：各折叠区直接渲染本函数结果，禁止再自行套一层
 *  「AI 暂时不可用（…）」，否则会出现「AI 暂时不可用（AI 暂时不可用（端点不可达））」式双层嵌套。
 */
export function aiUnavailableText(reason?: string | null): string {
  const key = reasonKey(reason);
  const text = AI_REASON_LABEL[key];
  if (!text) return "AI 暂时不可用"; // 无 reason / 未知码：整句兜底
  // disabled、status_error 本身已是完整语义，套前缀会歪曲原意
  return key === "disabled" || key === "status_error" ? text : `AI 暂时不可用（${text}）`;
}

/** 人话摘要固定免责注（后端 disclaimer 为空时前端兜底，禁止省略）。 */
export const AI_DISCLAIMER = "AI 生成，数值以上方表格为准";
