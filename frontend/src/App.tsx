import { useState } from "react";
import Library from "./pages/Library";
import Graph from "./pages/Graph";
import Chat from "./pages/Chat";
import Skills from "./pages/Skills";
import Settings from "./pages/Settings";

const NAV: [string, string][] = [
  ["library", "Library"],
  ["graph", "Graph"],
  ["chat", "Chat"],
  ["skills", "Skills"],
  ["settings", "Settings"],
];

export default function App() {
  const [page, setPage] = useState("library");
  return (
    <div className="min-h-screen flex">
      <nav className="w-52 shrink-0 bg-slate-900 text-slate-100 p-4 flex flex-col">
        <h1 className="text-xl font-bold mb-6 tracking-tight">PaperMind</h1>
        <div className="space-y-1">
          {NAV.map(([key, label]) => (
            <button
              key={key}
              onClick={() => setPage(key)}
              className={`block w-full text-left px-3 py-2 rounded-md transition ${
                page === key ? "bg-slate-700 font-medium" : "hover:bg-slate-800"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </nav>
      <main className="flex-1 p-6 overflow-auto">
        {page === "library" && <Library />}
        {page === "graph" && <Graph />}
        {page === "chat" && <Chat />}
        {page === "skills" && <Skills />}
        {page === "settings" && <Settings />}
      </main>
    </div>
  );
}
