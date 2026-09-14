import { useEffect } from "react";
import type { Clarification, ClarificationResponse } from "../api";
import { usePaperDraft } from "./usePaperDraft";

export function AskUserCard({ request, conversationId, disabled, onAnswer }: {
  request: Clarification;
  conversationId: number;
  disabled: boolean;
  onAnswer: (response: ClarificationResponse, text: string) => void;
}) {
  const [answers, setAnswers, clearDraft, storageError] = usePaperDraft<Record<string, string>>(
    request.message_id, {}, `ask-user-${conversationId}`,
  );
  const pending = request.status === "pending";
  useEffect(() => {
    if (!pending) clearDraft(answers);
  }, [request.status]);

  function submit() {
    const clean = Object.fromEntries(request.questions.map(q => [q.id, (answers[q.id] ?? "").trim()]));
    if (disabled || Object.values(clean).some(value => !value)) return;
    onAnswer({ message_id: request.message_id, answers: clean },
      "补充信息：\n" + request.questions.map(q => `${q.question}\n${clean[q.id]}`).join("\n\n"));
  }

  return <section aria-label="AI 向你提问" className="space-y-4 rounded-lg border p-4"
    style={{ borderColor: "var(--border)", backgroundColor: "var(--surface-2)" }}>
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium">{pending ? "补充这些信息，方便继续" : "需求补充"}</h3>
        <span className="text-xs text-muted" role="status">{pending ? "等待你的回答" : request.status === "skipped" ? "已跳过" : "已回答"}</span>
      </div>
      {request.reason && <p className="mt-2 whitespace-pre-wrap text-sm text-muted">{request.reason}</p>}
    </div>
    {request.questions.map((q, index) => <div key={q.id} className="space-y-2">
      <label className="block whitespace-pre-wrap text-sm font-medium" htmlFor={`ask-${request.message_id}-${q.id}`}>
        {request.questions.length > 1 ? `${index + 1}. ` : ""}{q.question}
      </label>
      {pending ? <>
        {q.options.length > 0 && <div className="flex flex-wrap gap-2" role="group" aria-label={`${q.question}：建议答案`}>
          {q.options.map(option => <button key={option} type="button" className="btn-ghost h-auto whitespace-normal text-left text-xs"
            disabled={disabled} aria-pressed={answers[q.id] === option}
            style={answers[q.id] === option ? { backgroundColor: "var(--accent-soft)", color: "var(--accent)", borderColor: "var(--accent)" } : {}}
            onClick={() => setAnswers({ ...answers, [q.id]: option })}>{option}</button>)}
        </div>}
        <textarea id={`ask-${request.message_id}-${q.id}`} className="input w-full resize-y text-sm" rows={2}
          disabled={disabled} maxLength={4000} placeholder="选择建议答案，或写下你的想法…"
          value={answers[q.id] ?? ""} onChange={e => setAnswers({ ...answers, [q.id]: e.target.value })} />
      </> : request.response?.answers?.[q.id] ? <p className="whitespace-pre-wrap text-sm text-muted">{request.response.answers[q.id]}</p> : null}
    </div>)}
    {!pending && request.response?.free_text && <p className="whitespace-pre-wrap text-sm text-muted">{request.response.free_text}</p>}
    {pending && <>
      <p className="text-xs text-muted">填写后继续原任务；也可以在下方输入框直接补充或调整需求。</p>
      {storageError && <p role="alert" className="text-xs text-[var(--danger)]">当前无法保存回答草稿，离开前请先提交。</p>}
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn-primary text-sm" disabled={disabled || request.questions.some(q => !(answers[q.id] ?? "").trim())} onClick={submit}>提交并继续</button>
        <button type="button" className="btn-ghost text-sm" disabled={disabled}
          onClick={() => onAnswer({ message_id: request.message_id, skipped: true }, "跳过这些问题，请根据已有信息继续，并说明必要的假设。")}>跳过，继续处理</button>
      </div>
    </>}
  </section>;
}
