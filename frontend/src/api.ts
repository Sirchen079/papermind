const BASE = "/api";

async function req<T = any>(path: string, opts?: RequestInit): Promise<T> {
  // Let the browser set the multipart boundary for FormData; force JSON otherwise.
  const isForm = typeof FormData !== "undefined" && opts?.body instanceof FormData;
  const res = await fetch(BASE + path, {
    ...opts,
    headers: {
      ...(isForm ? {} : { "Content-Type": "application/json" }),
      ...opts?.headers,
    },
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  if (res.status === 204) return null as T;
  return res.json();
}

export interface SseEvent {
  event: string;
  data: any;
}

/** POST to an SSE endpoint and yield parsed {event, data} frames as they arrive. */
export async function* sseStream(path: string, body: unknown): AsyncGenerator<SseEvent> {
  const res = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    throw new Error(`${res.status} ${await res.text()}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? ""; // keep the trailing partial frame
    for (const frame of frames) {
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (data) {
        try {
          yield { event, data: JSON.parse(data) };
        } catch {
          /* skip malformed frame */
        }
      }
    }
  }
}

export interface Paper {
  id: number;
  source: string;
  title: string | null;
  authors: string[];
  abstract: string | null;
  year: number | null;
  doi: string | null;
  arxiv_id: string | null;
  parse_confidence: number | null;
  has_summary?: boolean;
  summary?: Record<string, string> | null;
  full_text?: string | null;
}

export interface GraphData {
  nodes: { id: number; title?: string; name?: string; year?: number; type?: string }[];
  edges: { source: number; target: number; weight: number }[];
}

export interface RelatedPaper {
  title: string | null;
  authors: string[];
  year: number | null;
  doi: string | null;
  cited_by_count: number;
  openalex_id: string | null;
}

export interface Suggestion {
  id: number;
  kind: string;
  title: string;
  detail: Record<string, any>;
  status: "new" | "seen" | "dismissed" | "accepted";
  weight: number;
  created_at: string | null;
  paper?: { id: number; title: string | null } | null;
  related_paper?: { id: number; title: string | null } | null;
}

export interface Provider {
  id: number;
  name: string;
  type: string;
  base_url: string | null;
  enabled: boolean;
}

export interface Model {
  id: number;
  model_id: string;
  display_name: string | null;
  context_window: number | null;
  role_default: string | null;
}

export interface Source {
  paper_id: number;
  title: string;
  snippet: string;
}

export const api = {
  // papers
  listPapers: () => req<Paper[]>("/papers"),
  getPaper: (id: number) => req<Paper>(`/papers/${id}`),
  relatedPapers: (id: number) => req<RelatedPaper[]>(`/papers/${id}/related`),
  reindexLibrary: () => req<{ chunks: number }>("/papers/reindex", { method: "POST" }),
  ingestPdf: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return req<Paper>("/papers/pdf", { method: "POST", body: form });
  },
  ingestBibtex: (bibtex: string) =>
    req<Paper[]>("/papers/bibtex", { method: "POST", body: JSON.stringify({ bibtex }) }),
  ingestArxiv: (arxiv_id: string) =>
    req<Paper>("/papers/arxiv", { method: "POST", body: JSON.stringify({ arxiv_id }) }),
  // graph
  graph: (kind: "paper" | "concept", minPapers = 1) =>
    req<GraphData>(`/graph/${kind}?min_papers=${minPapers}`),
  // chat
  listConversations: () => req<{ id: number; title: string }[]>("/chat/conversations"),
  createConversation: () => req<{ id: number; title: string }>("/chat/conversations", { method: "POST" }),
  renameConversation: (id: number, title: string) =>
    req<{ id: number; title: string }>(`/chat/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  deleteConversation: (id: number) => req(`/chat/conversations/${id}`, { method: "DELETE" }),
  getConversation: (id: number) =>
    req<{
      id: number;
      title: string;
      messages: { role: string; content: string; model: string; sources: Source[] }[];
    }>(`/chat/conversations/${id}`),
  sendMessage: (id: number, content: string) =>
    req<{ role: string; content: string; model: string; tokens: number }>(
      `/chat/conversations/${id}/messages`,
      { method: "POST", body: JSON.stringify({ content }) }
    ),
  streamMessage: (id: number, content: string) =>
    sseStream(`/chat/conversations/${id}/messages/stream`, { content }),
  // providers / models
  listProviders: () => req<Provider[]>("/providers"),
  createProvider: (body: Record<string, unknown>) =>
    req<Provider>("/providers", { method: "POST", body: JSON.stringify(body) }),
  patchProvider: (id: number, body: Record<string, unknown>) =>
    req<Provider>(`/providers/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteProvider: (id: number) => req(`/providers/${id}`, { method: "DELETE" }),
  refreshModels: (id: number) => req<{ count: number }>(`/providers/${id}/models/refresh`, { method: "POST" }),
  addModel: (pid: number, body: { model_id: string; display_name?: string; role_default?: string }) =>
    req<Model>(`/providers/${pid}/models`, { method: "POST", body: JSON.stringify(body) }),
  providerModels: (id: number) => req<Model[]>(`/providers/${id}/models`),
  setModelRole: (id: number, role_default: string) =>
    req(`/models/${id}`, { method: "PATCH", body: JSON.stringify({ role_default }) }),
  // usage
  usage: (days = 30) =>
    req<{ total_tokens: number; by_kind: Record<string, number>; by_model: Record<string, number> }>(
      `/usage?days=${days}`
    ),
  // skills
  listSkills: () =>
    req<
      {
        id: number;
        name: string;
        type: string;
        trigger: string;
        keywords: string[];
        description: string | null;
        body: string | null;
        enabled: boolean;
        source: string;
      }[]
    >("/skills"),
  upsertSkill: (body: Record<string, unknown>) =>
    req("/skills", { method: "POST", body: JSON.stringify(body) }),
  deleteSkill: (id: number) => req(`/skills/${id}`, { method: "DELETE" }),
  reloadSkills: () => req<{ loaded: number }>("/skills/reload", { method: "POST" }),
  runSkill: (id: number, input = "") =>
    req<{ ok: boolean; stdout: string; stderr: string; exit_code: number; duration_ms: number }>(
      `/skills/${id}/run`,
      { method: "POST", body: JSON.stringify({ input }) },
    ),
  // suggestions
  listSuggestions: (status?: string) =>
    req<Suggestion[]>(`/suggestions${status ? `?status=${status}` : ""}`),
  patchSuggestion: (id: number, status: string) =>
    req<Suggestion>(`/suggestions/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  generateSuggestions: () => req<{ created: number }>("/suggestions/generate", { method: "POST" }),
};
