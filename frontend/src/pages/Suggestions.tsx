import { useEffect, useState } from "react";
import { api, Suggestion } from "../api";

export default function Suggestions({ onOpenPaper }: { onOpenPaper: (id: number) => void }) {
  const [items, setItems] = useState<Suggestion[]>([]);
  const [filter, setFilter] = useState<"new" | "all" | "accepted" | "dismissed">("new");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);

  async function load() {
    try {
      setItems(await api.listSuggestions(filter === "all" ? undefined : filter));
      setErr(null);
    } catch (e: any) {
      setErr(e.message);
    }
  }
  useEffect(() => {
    load();
  }, [filter]);

  async function scan() {
    setScanning(true);
    setErr(null);
    try {
      const r = await api.generateSuggestions();
      setMsg(r.created > 0 ? `${r.created} new suggestion(s) found.` : "Library is up to date.");
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setScanning(false);
    }
  }

  async function act(id: number, status: "accepted" | "dismissed" | "seen") {
    try {
      await api.patchSuggestion(id, status);
      await load();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  return (
    <div className="max-w-3xl space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex overflow-hidden rounded-lg" style={{ border: "1px solid var(--border)" }}>
          {(["new", "all", "accepted", "dismissed"] as const).map((f) => {
            const isActive = filter === f;
            return (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className="px-3 py-1.5 text-sm capitalize transition-colors"
                style={
                  isActive
                    ? { backgroundColor: "var(--accent)", color: "var(--accent-contrast)" }
                    : { backgroundColor: "var(--surface)", color: "var(--muted)" }
                }
              >
                {f}
              </button>
            );
          })}
        </div>
        <button onClick={scan} disabled={scanning} className="btn-primary">
          {scanning ? "Scanning…" : "↻ Scan library"}
        </button>
      </div>

      <p className="text-sm" style={{ color: "var(--muted)" }}>
        Connections the agent surfaces from your concept graph — papers that share themes, and concepts
        that span much of your library.
      </p>

      {msg && (
        <div
          className="rounded-lg px-3 py-2 text-sm"
          style={{ backgroundColor: "color-mix(in srgb, var(--success) 14%, transparent)", color: "var(--success)" }}
        >
          {msg}
        </div>
      )}
      {err && (
        <div
          className="rounded-lg px-3 py-2 text-sm"
          style={{ backgroundColor: "color-mix(in srgb, var(--danger) 12%, transparent)", color: "var(--danger)" }}
        >
          {err}
        </div>
      )}

      <div className="space-y-2">
        {items.length === 0 && (
          <div className="card text-center text-sm" style={{ color: "var(--muted)" }}>
            {filter === "new"
              ? "No new suggestions. Ingest papers with a provider configured, or scan the library."
              : `No ${filter} suggestions.`}
          </div>
        )}
        {items.map((s) => (
          <div key={s.id} className="card-tight" style={{ boxShadow: "var(--shadow)" }}>
            <div className="flex items-start gap-3">
              <div
                className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-sm"
                style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}
              >
                {s.kind === "concept_hub" ? "★" : "🔗"}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{s.title}</span>
                  <span className="chip">{s.kind === "concept_hub" ? "theme" : "link"}</span>
                  {s.status !== "new" && (
                    <span className="text-xs capitalize" style={{ color: "var(--faint)" }}>
                      {s.status}
                    </span>
                  )}
                </div>
                <div className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
                  {s.kind === "concept_link" && s.detail.shared_concepts && (
                    <span>
                      Shares {s.detail.count} concept(s): {s.detail.shared_concepts.join(", ")}
                    </span>
                  )}
                  {s.kind === "concept_hub" && (
                    <span>Appears across {s.detail.papers} paper(s) in your library.</span>
                  )}
                </div>
                {s.status === "new" && (
                  <div className="mt-2 flex gap-2">
                    <button onClick={() => act(s.id, "accepted")} className="btn-primary py-1 text-xs">
                      Useful
                    </button>
                    <button onClick={() => act(s.id, "dismissed")} className="btn-ghost py-1 text-xs">
                      Dismiss
                    </button>
                  </div>
                )}
                {s.kind === "concept_link" && (s.paper || s.related_paper) && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {s.paper && (
                      <button
                        onClick={() => onOpenPaper(s.paper!.id)}
                        className="inline-flex max-w-[220px] items-center gap-1 rounded-full px-2.5 py-1 text-xs"
                        style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}
                        title={s.paper.title ?? `#${s.paper.id}`}
                      >
                        📚 <span className="truncate">{s.paper.title ?? `#${s.paper.id}`}</span>
                      </button>
                    )}
                    {s.related_paper && (
                      <button
                        onClick={() => onOpenPaper(s.related_paper!.id)}
                        className="inline-flex max-w-[220px] items-center gap-1 rounded-full px-2.5 py-1 text-xs"
                        style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}
                        title={s.related_paper.title ?? `#${s.related_paper.id}`}
                      >
                        📚 <span className="truncate">
                          {s.related_paper.title ?? `#${s.related_paper.id}`}
                        </span>
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
