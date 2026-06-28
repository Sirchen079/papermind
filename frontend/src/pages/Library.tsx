import { useEffect, useState } from "react";
import { api, Paper, RelatedPaper } from "../api";

export default function Library() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bibtex, setBibtex] = useState("");
  const [arxivId, setArxivId] = useState("");
  const [selected, setSelected] = useState<Paper | null>(null);
  const [related, setRelated] = useState<RelatedPaper[] | null>(null);
  const [relatedLoading, setRelatedLoading] = useState(false);
  const [relatedError, setRelatedError] = useState(false);

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

  return (
    <div className="max-w-5xl">
      <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="card">
          <h3 className="mb-3 font-semibold">Add from BibTeX</h3>
          <textarea
            className="input h-24 font-mono resize-none"
            placeholder="@article{...}"
            value={bibtex}
            onChange={(e) => setBibtex(e.target.value)}
          />
          <button onClick={ingestBibtex} disabled={loading} className="btn-primary mt-3">
            Ingest
          </button>
        </div>
        <div className="card">
          <h3 className="mb-3 font-semibold">Add from ArXiv</h3>
          <input
            className="input"
            placeholder="e.g. 1706.03762"
            value={arxivId}
            onChange={(e) => setArxivId(e.target.value)}
          />
          <button onClick={ingestArxiv} disabled={loading} className="btn-primary mt-3">
            Fetch &amp; ingest
          </button>
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

      <div className="space-y-2">
        {papers.length === 0 && !loading && (
          <div className="card text-center" style={{ color: "var(--muted)" }}>
            No papers yet — add one above to let the agent parse, summarize, and graph it.
          </div>
        )}
        {papers.map((p) => (
          <button
            key={p.id}
            onClick={() => open(p)}
            className="card-tight block w-full text-left transition hover:translate-y-[-1px]"
            style={{ boxShadow: "var(--shadow)" }}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="font-medium">{p.title ?? "(untitled)"}</div>
              {p.has_summary && <span className="chip shrink-0">summarized</span>}
            </div>
            <div className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
              {p.authors.slice(0, 3).join(", ")}
              {p.authors.length > 3 ? " et al." : ""} {p.year ? `· ${p.year}` : ""}
            </div>
          </button>
        ))}
      </div>

      {selected && (
        <div
          className="fixed inset-0 flex items-center justify-center p-6"
          style={{ backgroundColor: "rgb(0 0 0 / 0.5)" }}
          onClick={() => setSelected(null)}
        >
          <div
            className="max-h-[82vh] w-full max-w-2xl overflow-auto rounded-xl p-6"
            style={{ backgroundColor: "var(--surface)", boxShadow: "var(--shadow-md)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-2 flex items-start justify-between gap-4">
              <h3 className="text-xl font-bold leading-snug">{selected.title}</h3>
              <button onClick={() => setSelected(null)} className="btn-subtle shrink-0 px-2">
                ✕
              </button>
            </div>
            <p className="mb-4 text-sm" style={{ color: "var(--muted)" }}>
              {selected.authors.join(", ")} {selected.year ? `· ${selected.year}` : ""}
            </p>
            {selected.abstract && <p className="mb-4 text-sm leading-relaxed">{selected.abstract}</p>}
            {selected.summary ? (
              <div className="space-y-2">
                <h4 className="font-semibold">AI Summary</h4>
                {Object.entries(selected.summary).map(([k, v]) => (
                  <div key={k} className="text-sm">
                    <span className="font-medium capitalize">{k}: </span>
                    {v}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm" style={{ color: "var(--faint)" }}>
                No AI summary (configure a provider in Settings).
              </p>
            )}

            <div className="mt-6 border-t pt-4" style={{ borderColor: "var(--border)" }}>
              <div className="mb-2 flex items-center gap-3">
                <h4 className="font-semibold">Related works</h4>
                <button onClick={() => findRelated(selected.id)} disabled={relatedLoading} className="btn-ghost">
                  {relatedLoading ? "Searching…" : "Find related (external)"}
                </button>
              </div>
              <p className="mb-2 text-xs" style={{ color: "var(--faint)" }}>
                Discovery via OpenAlex — searches outside your library. Network errors degrade to an empty list.
              </p>
              {relatedError && !relatedLoading && (
                <p className="text-sm" style={{ color: "var(--danger)" }}>
                  Discovery failed (network/API error). Try again.
                </p>
              )}
              {related !== null && related.length === 0 && !relatedLoading && !relatedError && (
                <p className="text-sm" style={{ color: "var(--faint)" }}>
                  No related works found.
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
                            {r.title ?? "(untitled)"}
                          </a>
                        ) : (
                          r.title ?? "(untitled)"
                        )}
                      </div>
                      <div className="mt-0.5 text-xs" style={{ color: "var(--muted)" }}>
                        {r.authors.slice(0, 3).join(", ")}
                        {r.authors.length > 3 ? " et al." : ""} {r.year ? `· ${r.year}` : ""}
                        {r.cited_by_count ? ` · cited by ${r.cited_by_count}` : ""}
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
