/**
 * 解析后端错误响应为「<status> <message>」形式的人类可读消息。
 * 优先读取 FastAPI 风格的 detail（字符串或 {msg} 对象数组），
 * 否则回退到原始响应体（trim 后最多 200 字符），空体使用默认文案。
 */
export function parseApiErrorMessage(status: number, bodyText: string): string {
  let message = "";
  try {
    const parsed: unknown = JSON.parse(bodyText);
    if (typeof parsed === "object" && parsed !== null && "detail" in parsed) {
      const parsedRecord: Record<string, unknown> = parsed as Record<string, unknown>;
      const detail: unknown = parsedRecord["detail"];
      if (typeof detail === "string" && detail.trim() !== "") {
        message = detail;
      } else if (Array.isArray(detail)) {
        const items: unknown[] = detail;
        const msgs: string[] = [];
        for (const item of items) {
          if (typeof item !== "object" || item === null) continue;
          const record: Record<string, unknown> = item as Record<string, unknown>;
          const msg: unknown = record["msg"];
          if (typeof msg === "string" && msg.trim() !== "") {
            msgs.push(msg);
          }
        }
        if (msgs.length > 0) {
          message = msgs.join("; ");
        }
      }
    }
  } catch {
    // 非 JSON 响应体：走下方原始文本回退
  }
  if (message === "") {
    const trimmed: string = bodyText.trim();
    message = trimmed !== "" ? trimmed.slice(0, 200) : "请求失败";
  }
  return `${status} ${message}`;
}
