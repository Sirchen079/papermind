import { useEffect, useState } from "react";
import { api, Paper, RelatedPaper } from "../api";

// 摘要字段键是固定的英文标识（由后端结构化），这里只做中文展示。
const SUMMARY_LABELS: Record<string, string> = {
  problem: "问题",
  method: "方法",
  dataset: "数据集",
  results: "结果",
  limitations: "局限",
  freeform: "概要",
};

export default function Library({
  openPaperId,
  onConsumedOpen,
}: {
  openPaperId: number | null;
  onConsumedOpen: () => void;
}) {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bibtex, setBibtex] = useState("");
  const [arxivId, setArxivId] = useState("");
  const [selected, setSelected] = useState<Paper | null>(null);
  const [related, setRelated] = useState<RelatedPaper[] | null>(null);
  const [relatedLoading, setRelatedLoading] = useState(false);
  const [relatedError, setRelatedError] = useState(false);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"year_desc" | "year_asc" | "title">("year_desc");
  const [analyzing, setAnalyzing] = useState(false);

  async function load() {
    setLoading(true);
    try {
      setPapers(await api.listPapers());
      setError(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  // Close the detail modal on Escape (keyboard parity with the overlay click).
  useEffect(() => {
    if (!selected) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setSelected(null);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected]);

  // Open a specific paper when navigated to from elsewhere (e.g. a Chat source).
  useEffect(() => {
    if (openPaperId == null) return;
    let alive = true;
    api
      .getPaper(openPaperId)
      .then((p) => {
        if (!alive) return;
        setSelected(p);
        setRelated(null);
        setRelatedError(false);
      })
      .catch(() => {})
      .finally(onConsumedOpen);
    return () => {
      alive = false;
    };
  }, [openPaperId, onConsumedOpen]);

  async function ingestBibtex() {
    if (!bibtex.trim()) return;
    setLoading(true);
    try {
      await api.ingestBibtex(bibtex);
      setBibtex("");
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function ingestArxiv() {
    if (!arxivId.trim()) return;
    setLoading(true);
    try {
      await api.ingestArxiv(arxivId.trim());
      setArxivId("");
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function open(p: Paper) {
    setSelected(await api.getPaper(p.id));
    setRelated(null);
  }

  async function findRelated(id: number) {
    setRelatedLoading(true);
    setRelatedError(false);
    try {
      setRelated(await api.relatedPapers(id));
    } catch {
      setRelated(null);
      setRelatedError(true);
    } finally {
      setRelatedLoading(false);
    }
  }

  async function removePaper(p: Paper) {
    if (!window.confirm(`从论文库移除「${p.title ?? "该论文"}」？`)) return;
    try {
      await api.deletePaper(p.id);
      if (selected?.id === p.id) setSelected(null);
      await load();
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function reanalyze() {
    if (!selected || analyzing) return;
    setAnalyzing(true);
    try {
      const res = await api.reanalyzePaper(selected.id);
      setSelected({ ...selected, summary: res.summary, concepts: res.concepts });
    } catch (e: any) {
      setError(e.message);
    } finally {
      setAnalyzing(false);
    }
  }

  // Client-side filter + sort — the library is local and small; a round-trip
  // per keystroke would be wasteful.
  const visible = papers
    .filter((p) => {
      const q = query.trim().toLowerCase();
      if (!q) return true;
      const hay = [
        p.title ?? "",
        p.authors.join(" "),
        (p.concepts ?? []).map((c) => c.name).join(" "),
        p.abstract ?? "",
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    })
    .sort((a, b) => {
      if (sort === "title") return (a.title ?? "").localeCompare(b.title ?? "");
      const dy = (b.year ?? 0) - (a.year ?? 0);
      return sort === "year_asc" ? -dy : dy;
    });

  return (
    <div className="max-w-5xl">
      <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="card">
          <h3 className="mb-3 font-semibold">从 BibTeX 添加</h3>
          <textarea
            className="input h-24 font-mono resize-none"
            placeholder="@article{...}"
            value={bibtex}
            onChange={(e) => setBibtex(e.target.value)}
          />
          <button onClick={ingestBibtex} disabled={loading} className="btn-primary mt-3">
            导入
          </button>
        </div>
        <div className="card">
          <h3 className="mb-3 font-semibold">从 ArXiv 添加</h3>
          <input
            className="input"
            placeholder="例如 1706.03762"
            value={arxivId}
            onChange={(e) => setArxivId(e.target.value)}
          />
          <button onClick={ingestArxiv} disabled={loading} className="btn-primary mt-3">
            获取并导入
          </button>
        </div>
        <div className="card">
          <h3 className="mb-3 font-semibold">上传 PDF</h3>
          <label className={`btn-primary inline-block cursor-pointer ${loading ? "opacity-60" : ""}`}>
            选择 PDF…
            <input
              type="file"
              accept="application/pdf"
              className="hidden"
              disabled={loading}
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (!f) return;
                setLoading(true);
                try {
                  await api.ingestPdf(f);
                  await load();
                } catch (err: any) {
                  setError(err.message);
                } finally {
                  setLoading(false);
                  e.target.value = "";
                }
              }}
            />
          </label>
          <p className="mt-2 text-xs" style={{ color: "var(--faint)" }}>
            通过 PyMuPDF 在本地提取文本。扫描版 / 纯图片 PDF 提取效果有限。
          </p>
        </div>
      </div>

      {error && (
        <div
          className="mb-4 rounded-lg px-3 py-2 text-sm"
          style={{ backgroundColor: "color-mix(in srgb, var(--danger) 12%, transparent)", color: "var(--danger)" }}
        >
          {error}
        </div>
      )}

      {papers.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <input
            className="input max-w-xs"
            placeholder="搜索标题、作者、概念…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select
            className="input max-w-[10rem]"
            value={sort}
            onChange={(e) => setSort(e.target.value as typeof sort)}
          >
            <option value="year_desc">最新优先</option>
            <option value="year_asc">最旧优先</option>
            <option value="title">按标题 A→Z</option>
          </select>
          <span className="text-xs" style={{ color: "var(--faint)" }}>
            {visible.length} / {papers.length}
          </span>
        </div>
      )}

      <div className="space-y-2">
        {papers.length === 0 && !loading && (
          <div className="card text-center" style={{ color: "var(--muted)" }}>
            还没有论文——在上方添加一篇，让 agent 自动解析、总结并构建图谱。
          </div>
        )}
        {visible.length === 0 && papers.length > 0 && (
          <div className="card text-center" style={{ color: "var(--muted)" }}>
            没有匹配「{query}」的论文。
          </div>
        )}
        {visible.map((p) => (
          <div
            key={p.id}
            className="card-tight group flex items-center gap-2 transition hover:translate-y-[-1px]"
            style={{ boxShadow: "var(--shadow)" }}
          >
            <button onClick={() => open(p)} className="block flex-1 text-left">
              <div className="flex items-start justify-between gap-3">
                <div className="font-medium">{p.title ?? "（无标题）"}</div>
                {p.has_summary && <span className="chip shrink-0">已总结</span>}
              </div>
              <div className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
                {p.authors.slice(0, 3).join(", ")}
                {p.authors.length > 3 ? " et al." : ""} {p.year ? `· ${p.year}` : ""}
              </div>
            </button>
            <button
              onClick={() => removePaper(p)}
              className="shrink-0 rounded-lg px-2 py-1 text-xs opacity-0 transition-opacity group-hover:opacity-100"
              style={{ color: "var(--faint)" }}
              title="从库中移除"
            >
              ✕
            </button>
          </div>
        ))}
      </div>

      {selected && (
        <div
          className="fixed inset-0 flex items-center justify-center p-6"
          style={{ backgroundColor: "rgb(0 0 0 / 0.5)" }}
          onClick={() => setSelected(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label={selected.title ?? "论文详情"}
            className="max-h-[82vh] w-full max-w-2xl overflow-auto rounded-xl p-6"
            style={{ backgroundColor: "var(--surface)", boxShadow: "var(--shadow-md)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-2 flex items-start justify-between gap-4">
              <h3 className="text-xl font-bold leading-snug">{selected.title ?? "（无标题）"}</h3>
              <button
                onClick={() => setSelected(null)}
                className="btn-subtle shrink-0 px-2"
                aria-label="关闭"
              >
                ✕
              </button>
            </div>
            <p className="mb-4 text-sm" style={{ color: "var(--muted)" }}>
              {selected.authors.join(", ")} {selected.year ? `· ${selected.year}` : ""}
            </p>
            {selected.abstract && <p className="mb-4 text-sm leading-relaxed">{selected.abstract}</p>}
            {selected.concepts && selected.concepts.length > 0 && (
              <div className="mb-4 flex flex-wrap gap-1.5">
                {selected.concepts.map((c, i) => (
                  <span key={i} className="chip">
                    {c.name}
                  </span>
                ))}
              </div>
            )}
            {selected.parse_confidence != null && selected.parse_confidence < 0.3 && (
              <div
                className="mb-4 rounded-lg px-3 py-2 text-sm"
                style={{
                  backgroundColor: "color-mix(in srgb, var(--danger) 10%, transparent)",
                  color: "var(--danger)",
                }}
              >
                文本提取质量较低（{Math.round(selected.parse_confidence * 100)}%）。这看起来是扫描版
                PDF——AI 摘要与全文检索会受限。
              </div>
            )}
            {selected.summary ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <h4 className="font-semibold">AI 摘要</h4>
                  <button onClick={reanalyze} disabled={analyzing} className="btn-ghost px-2.5 py-1 text-xs">
                    {analyzing ? "重新分析中…" : "↻ 重新分析"}
                  </button>
                </div>
                {Object.entries(selected.summary).map(([k, v]) => (
                  <div key={k} className="text-sm">
                    <span className="font-medium">{SUMMARY_LABELS[k] ?? k}：</span>
                    {v}
                  </div>
                ))}
              </div>
            ) : (
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  {selected.analysis?.status === "failed" ? (
                    <p className="text-sm" style={{ color: "var(--danger)" }}>
                      上次分析失败{selected.analysis.error ? `：${selected.analysis.error}` : ""}。
                    </p>
                  ) : (
                    <p className="text-sm" style={{ color: "var(--faint)" }}>
                      暂无 AI 摘要（请在「设置」中为某个模型分配 LLM 角色）。
                    </p>
                  )}
                  <button onClick={reanalyze} disabled={analyzing} className="btn-ghost px-2.5 py-1 text-xs">
                    {analyzing
                      ? "分析中…"
                      : selected.analysis?.status === "failed"
                        ? "↻ 重试分析"
                        : "↻ 立即分析"}
                  </button>
                </div>
              </div>
            )}

            <div className="mt-6 border-t pt-4" style={{ borderColor: "var(--border)" }}>
              <div className="mb-2 flex items-center gap-3">
                <h4 className="font-semibold">相关研究</h4>
                <button onClick={() => findRelated(selected.id)} disabled={relatedLoading} className="btn-ghost">
                  {relatedLoading ? "搜索中…" : "查找相关（库外）"}
                </button>
              </div>
              <p className="mb-2 text-xs" style={{ color: "var(--faint)" }}>
                通过 OpenAlex 发现——搜索你的论文库之外的研究。网络错误时返回空列表。
              </p>
              {relatedError && !relatedLoading && (
                <p className="text-sm" style={{ color: "var(--danger)" }}>
                  发现失败（网络 / API 错误）。请重试。
                </p>
              )}
              {related !== null && related.length === 0 && !relatedLoading && !relatedError && (
                <p className="text-sm" style={{ color: "var(--faint)" }}>
                  未找到相关研究。
                </p>
              )}
              {related && related.length > 0 && (
                <ul className="space-y-2">
                  {related.map((r) => (
                    <li
                      key={r.openalex_id ?? r.title ?? Math.random()}
                      className="rounded-lg p-2.5 text-sm"
                      style={{ backgroundColor: "var(--surface-2)" }}
                    >
                      <div className="font-medium">
                        {r.doi ? (
                          <a
                            href={`https://doi.org/${r.doi}`}
                            target="_blank"
                            rel="noreferrer"
                            style={{ color: "var(--accent)" }}
                            className="hover:underline"
                          >
                            {r.title ?? "（无标题）"}
                          </a>
                        ) : (
                          r.title ?? "（无标题）"
                        )}
                      </div>
                      <div className="mt-0.5 text-xs" style={{ color: "var(--muted)" }}>
                        {r.authors.slice(0, 3).join(", ")}
                        {r.authors.length > 3 ? " 等" : ""} {r.year ? `· ${r.year}` : ""}
                        {r.cited_by_count ? ` · 被引 ${r.cited_by_count}` : ""}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
