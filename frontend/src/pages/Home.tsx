import { useApi } from '../workspaceContext';
import { useEffect, useState } from "react";
import { type Paper, type RecentlyReadPaper } from "../api";
import { Shell } from "../components/layout/Shell";
import ReadinessPanel from "../components/ReadinessPanel";
import ResearchProgressPanel from "../components/ResearchProgressPanel";
import GroupMeetingPanel from "../components/GroupMeetingPanel";
import LibraryDiagnosticsPanel from "../components/LibraryDiagnosticsPanel";
import type { NavLocation } from "./navigationModel";
import { ReadingDesk } from '../components/ReadingDesk';
import ResearchLaunch from '../components/ResearchLaunch';
import { BookOpen, Sparkles, Logo, Settings } from '../icons';
import { EmptyState } from '../components/ui/EmptyState';

const READING_STATUS_LABELS: Record<string, string> = {
  unread: "未读",
  queued: "待读",
  reading: "阅读中",
  read: "已读",
  skipped: "跳过",
};

function paperSubtitle(item: { authors: string[]; year: number | null; venue: string | null }) {
  const parts: string[] = [];
  if (item.authors.length > 0) parts.push(item.authors.slice(0, 3).join(", "));
  if (item.year != null) parts.push(String(item.year));
  if (item.venue) parts.push(item.venue);
  return parts.join(" · ");
}

/**
 * The homepage prioritizes import, reading and question-driven research.
 * Progress and diagnostics mount only when explicitly expanded.
 */
export default function Home({
  onOpenPaper,
  onNavigate,
  guided=false,
}: {
  onOpenPaper: (id: number) => void;
  onNavigate?: (target: NavLocation | string) => void;
  guided?: boolean;
}) {
  const api = useApi();
  const [recentlyRead, setRecentlyRead] = useState<RecentlyReadPaper[] | null>(null);
  const [recentImports, setRecentImports] = useState<Paper[] | null>(null);
  const [loadingError, setLoadingError] = useState<string | null>(null);
  const [showProgress,setShowProgress] = useState(false);
  const [showChecks,setShowChecks] = useState(false);
  const [showDesk,setShowDesk] = useState(false);

  useEffect(() => {
    let alive = true;
    Promise.all([api.recentlyRead(5), api.listPapers(5)])
      .then(([read, imported]) => {
        if (!alive) return;
        setRecentlyRead(read);
        setRecentImports(imported.items);
        setLoadingError(null);
      })
      .catch((e: any) => {
        if (alive) setLoadingError(e?.message ?? "最近工作加载失败");
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <Shell max="wide" className="home-workspace">
      <div className="workspace-masthead"><div><p className="workspace-kicker">PAPERMIND / RESEARCH NOTEBOOK</p><p className="workspace-caption">每一次阅读，都让问题更清楚。</p></div><time dateTime={new Date().toLocaleDateString('en-CA')}>{new Date().toLocaleDateString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',weekday:'long'})}</time></div>
      {!guided&&<ResearchLaunch papers={recentImports??[]} onNavigate={onNavigate}/>}
      {loadingError&&<p role="alert" className="alert alert-danger mb-4">最近工作加载失败：{loadingError}</p>}

      <div className="home-section-label"><span>01 / MATERIALS</span><h2>从手头的材料出发</h2><span className="section-rule"/></div>
      <section aria-label="从这里开始" className="start-grid">
        <div className="start-card"><div className="start-card-top"><span className="start-icon"><Logo size={22}/></span></div><h2 className="font-semibold">把论文交给 PaperMind</h2><p className="text-sm text-muted flex-1">导入 PDF，原文、摘录和后续研究放在一起。</p><button className="btn-ghost" onClick={()=>onNavigate?.({page:'library',params:{import:'pdf'}})}>导入论文 <span aria-hidden="true">↗</span></button></div>
        <div className="start-card"><div className="start-card-top"><span className="start-icon"><BookOpen size={22}/></span></div><h2 className="font-semibold">接着刚才读到的地方</h2><p className="text-sm text-muted flex-1">回到论文与笔记，不用重新找材料。</p><button className="btn-ghost" onClick={()=>recentlyRead?.[0]?onOpenPaper(recentlyRead[0].id):recentImports?.[0]?onOpenPaper(recentImports[0].id):onNavigate?.('library')}>{recentlyRead?.length?'继续上次阅读':'打开论文库'} <span aria-hidden="true">↗</span></button></div>
        <div className="start-card"><div className="start-card-top"><span className="start-icon"><Sparkles size={22}/></span></div><h2 className="font-semibold">卡在一句话？直接问</h2><p className="text-sm text-muted flex-1">让 AI 解释概念、梳理思路，围绕论文继续聊。</p><button className="btn-ghost" onClick={()=>onNavigate?.('chat')}>打开论文问答 <span aria-hidden="true">↗</span></button></div>
      </section>

      {Boolean(recentlyRead?.length||recentImports?.length)&&<div className="home-recent-grid mb-4 grid grid-cols-1 gap-5 lg:grid-cols-2">
        <section className="recent-section research-shelf" aria-label="继续阅读">
          <div className="mb-3 flex items-center justify-between gap-2">
            <h3 className="shelf-heading"><BookOpen size={18}/><span>继续阅读<small>READING SPACE</small></span></h3>
            <button
              className="btn-ghost py-1 text-xs"
              onClick={() => onNavigate?.({ page: "library", params: { status: "reading" } })}
            >
              阅读中的论文
            </button>
          </div>
          {recentlyRead == null ? (
            <p className="text-sm text-faint">正在加载最近阅读…</p>
          ) : recentlyRead.length === 0 ? (
            <EmptyState className="shelf-empty" icon={<BookOpen size={24}/>} title="阅读，从这里接上" hint="论文、摘录和上次读到的位置，留在同一个地方。" action={<button className="btn-ghost" onClick={()=>onNavigate?.('library')}>去论文库 <span aria-hidden="true">↗</span></button>}/>
          ) : (
            <ul className="space-y-2">
              {recentlyRead.map((item) => (
                <li key={item.id}>
                  <button
                    onClick={() => onOpenPaper(item.id)}
                    className="shelf-paper w-full text-left"
                  >
                    <span className="paper-specimen" aria-hidden="true"><BookOpen size={20}/><i/><i/><i/></span>
                    <span className="shelf-paper-content"><span className="shelf-paper-title">
                      <span className="truncate text-sm font-medium">{item.title ?? "未命名论文"}</span>
                      <span className="shelf-paper-tag">
                        {READING_STATUS_LABELS[item.status] ?? item.status}
                        {item.last_page != null ? ` · 第 ${item.last_page} 页` : ""}
                      </span>
                    </span>
                    <span className="shelf-paper-meta">{paperSubtitle(item)||'原文与阅读笔记'}</span></span>
                    <span className="shelf-paper-arrow" aria-hidden="true">↗</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="recent-section research-shelf" aria-label="最近导入">
          <div className="mb-3 flex items-center justify-between gap-2">
            <h3 className="shelf-heading"><Logo size={18}/><span>最近导入<small>PAPER COLLECTION</small></span></h3>
            <button className="btn-ghost py-1 text-xs" onClick={() => onNavigate?.("library")}>
              查看论文库
            </button>
          </div>
          {recentImports == null ? (
            <p className="text-sm text-faint">正在加载最近导入…</p>
          ) : recentImports.length === 0 ? (
            <div className="text-sm text-muted">
              论文库还是空的。先导入手头的一篇 PDF 就好。
              <div className="mt-2 flex flex-wrap gap-2">
                <button
                  className="btn-primary py-1 text-xs"
                  onClick={() => onNavigate?.({ page: "library", params: { import: "pdf" } })}
                >
                  直接导入
                </button>
              </div>
            </div>
          ) : (
            <ul className="space-y-2">
              {recentImports.map((item) => (
                <li key={item.id}>
                  <button
                    onClick={() => onOpenPaper(item.id)}
                    className="shelf-paper w-full text-left"
                  >
                    <span className="paper-specimen" aria-hidden="true"><Logo size={20}/><i/><i/><i/></span>
                    <span className="shelf-paper-content"><span className="shelf-paper-title">
                      <span className="truncate text-sm font-medium">{item.title ?? "未命名论文"}</span>
                      {item.has_summary ? (
                        <span className="shelf-paper-tag" style={{ color: "var(--success)" }}>
                          已分析
                        </span>
                      ) : (
                        <span className="shelf-paper-tag">已收藏</span>
                      )}
                    </span>
                    <span className="shelf-paper-meta">{paperSubtitle(item)||'个人论文收藏'}</span>
                    {item.abstract&&<span className="shelf-paper-abstract">{item.abstract}</span>}</span>
                    <span className="shelf-paper-arrow" aria-hidden="true">↗</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>}

      {Boolean(recentImports?.length)&&<details className="home-detail research-tool" onToggle={e=>setShowDesk(e.currentTarget.open)}><summary><span className="research-tool-icon"><BookOpen size={20}/></span><span><strong>翻看最近收藏</strong><small>在阅读台浏览论文，遇到感兴趣的内容就打开</small></span></summary>{showDesk&&<div className="py-6"><ReadingDesk papers={recentImports??[]} onOpenPaper={onOpenPaper}/></div>}</details>}
      <details className="home-detail research-tool" onToggle={e=>setShowProgress(e.currentTarget.open)}><summary><span className="research-tool-icon"><Sparkles size={20}/></span><span><strong>组会素材与研究进度</strong><small>找回可复用的材料，接上已有研究</small></span></summary>{showProgress&&<><ResearchProgressPanel onNavigate={onNavigate}/><GroupMeetingPanel/></>}</details>
      <details className="home-detail research-tool" onToggle={e=>setShowChecks(e.currentTarget.open)}><summary><span className="research-tool-icon"><Settings size={20}/></span><span><strong>检查 AI 配置与论文资料</strong><small>需要时查看模型连接与材料状态</small></span></summary>{showChecks&&<><ReadinessPanel onNavigate={onNavigate}/><LibraryDiagnosticsPanel onOpenPaper={onOpenPaper} onNavigate={onNavigate}/></>}</details>
    </Shell>
  );
}
