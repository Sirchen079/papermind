import { useEffect, useState } from "react";
import { api, Paper } from "../api";

export default function Library() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bibtex, setBibtex] = useState("");
  const [arxivId, setArxivId] = useState("");
  const [selected, setSelected] = useState<Paper | null>(null);

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
  }

  return (
    <div className="max-w-5xl">
      <h2 className="text-2xl font-bold mb-4">Library</h2>

      <div className="grid grid-cols-2 gap-4 mb-6">
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="font-semibold mb-2">Add from BibTeX</h3>
          <textarea
            className="w-full border rounded p-2 text-sm font-mono h-24"
            placeholder="@article{...}"
            value={bibtex}
            onChange={(e) => setBibtex(e.target.value)}
          />
          <button
            onClick={ingestBibtex}
            disabled={loading}
            className="mt-2 bg-slate-900 text-white px-3 py-1.5 rounded text-sm disabled:opacity-50"
          >
            Ingest
          </button>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="font-semibold mb-2">Add from ArXiv</h3>
          <input
            className="w-full border rounded p-2 text-sm"
            placeholder="e.g. 1706.03762"
            value={arxivId}
            onChange={(e) => setArxivId(e.target.value)}
          />
          <button
            onClick={ingestArxiv}
            disabled={loading}
            className="mt-2 bg-slate-900 text-white px-3 py-1.5 rounded text-sm disabled:opacity-50"
          >
            Fetch &amp; ingest
          </button>
        </div>
      </div>

      {error && <div className="text-red-600 text-sm mb-4">{error}</div>}

      <div className="space-y-2">
        {papers.length === 0 && !loading && (
          <p className="text-slate-500">No papers yet. Add one above.</p>
        )}
        {papers.map((p) => (
          <button
            key={p.id}
            onClick={() => open(p)}
            className="block w-full text-left bg-white rounded-lg shadow p-3 hover:shadow-md transition"
          >
            <div className="font-medium">{p.title ?? "(untitled)"}</div>
            <div className="text-sm text-slate-500">
              {p.authors.slice(0, 3).join(", ")}
              {p.authors.length > 3 ? " et al." : ""} {p.year ? `· ${p.year}` : ""}
              {p.has_summary ? " · ✓ summarized" : ""}
            </div>
          </button>
        ))}
      </div>

      {selected && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center p-6" onClick={() => setSelected(null)}>
          <div className="bg-white rounded-lg max-w-2xl w-full max-h-[80vh] overflow-auto p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-start mb-2">
              <h3 className="text-xl font-bold">{selected.title}</h3>
              <button onClick={() => setSelected(null)} className="text-slate-400 hover:text-slate-700">✕</button>
            </div>
            <p className="text-sm text-slate-500 mb-4">
              {selected.authors.join(", ")} {selected.year ? `· ${selected.year}` : ""}
            </p>
            {selected.abstract && <p className="text-sm mb-4">{selected.abstract}</p>}
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
              <p className="text-sm text-slate-400">No AI summary (configure a provider in Settings).</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
