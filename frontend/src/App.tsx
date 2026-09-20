import { useApi, useWorkspace, workspaceDraftKey } from './workspaceContext';
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useTheme, type Theme } from "./theme";
import { Menu, Moon, Sun } from "./icons";
import { ConfirmProvider } from "./components/ui/ConfirmDialog";
import { ToastProvider } from "./components/ui/Toast";
import { Skeleton, SkeletonGroup } from "./components/ui/Skeleton";
import {
  DEFAULT_PAGE,
  buildHash,
  normalizePage,
  parseHash,
  sameLocation,
  type NavLocation,
} from "./pages/navigationModel";
import type { PaperChatContext } from "./pages/chatContextModel";
import { readConversationContext, restoreConversationContext, saveConversationContext } from './pages/conversationDraftModel';
import { libraryScope, localStore } from './components/usePaperDraft';
import { GettingStarted, useGettingStarted } from './components/GettingStarted';
import { Sidebar, pageLabels } from './components/layout/Sidebar';
import { Shell } from './components/layout/Shell';

// Route-level code splitting keeps the heavy graph lib (cytoscape) out of the
// initial bundle — it only loads when the Graph page is opened.
const Library = lazy(() => import("./pages/Library"));
const Graph = lazy(() => import("./pages/Graph"));
const Chat = lazy(() => import("./pages/Chat"));
const Skills = lazy(() => import("./pages/Skills"));
const Settings = lazy(() => import("./pages/Settings"));
const Suggestions = lazy(() => import("./pages/Suggestions"));
const Ideas = lazy(() => import("./pages/Ideas"));
const Home = lazy(() => import("./pages/Home"));
const Research = lazy(() => import("./pages/Research"));
const Wiki = lazy(() => import('./pages/Wiki'));
const Help = lazy(() => import('./pages/Help'));

function readInitialLocation(): NavLocation {
  if (typeof window === "undefined") return { page: DEFAULT_PAGE, params: {} };
  return parseHash(window.location.hash);
}

function ThemeToggle({ theme, toggle }: { theme: Theme; toggle: () => void }) {
  const isDark = theme === "dark";
  return (
    <button
      onClick={toggle}
      className="btn-subtle p-2"
      title={`切换到${isDark ? "浅色" : "深色"}模式`}
      aria-label={`切换到${isDark ? "浅色" : "深色"}模式`}
    >
      {isDark ? <Sun size={16} /> : <Moon size={16} />}
      <span className="sr-only">{isDark ? "浅色模式" : "深色模式"}</span>
    </button>
  );
}

export default function App() {
  const api = useApi();
  const {workspace}=useWorkspace();
  const conversationKey=workspaceDraftKey(workspace.id,'pm-active-conversation');
  const [location, setLocation] = useState<NavLocation>(readInitialLocation);
  const [newCount, setNewCount] = useState(0);
  const [openPaperId, setOpenPaperId] = useState<number | null>(null);
  const [activeConv, setActiveConv] = useState<number | null>(()=>{
    const explicit=location.page==='chat'?Number(location.params.conversation):0;
    if(Number.isSafeInteger(explicit)&&explicit>0)return explicit;
    try{const id=Number(localStorage.getItem(conversationKey));return Number.isSafeInteger(id)&&id>0?id:null;}catch{return null;}
  });
  useEffect(()=>{try{if(activeConv===null)localStorage.removeItem(conversationKey);else localStorage.setItem(conversationKey,String(activeConv));}catch{}},[activeConv,conversationKey]);
  const [chatContexts, setChatContexts] = useState<Record<number, PaperChatContext>>(()=>{
    const saved=activeConv===null?null:readConversationContext(localStore(),libraryScope(),workspace.id,activeConv);
    return saved&&activeConv!==null?{[activeConv]:saved}:{};
  });
  const [contextStorageError,setContextStorageError]=useState(false);
  const storeChatContext=useCallback((id:number,context:PaperChatContext|null)=>{
    setContextStorageError(!saveConversationContext(localStore(),libraryScope(),workspace.id,id,context));
    setChatContexts(prev=>{const next={...prev};if(context)next[id]=context;else delete next[id];return next;});
  },[workspace.id]);
  const [chatOpenError, setChatOpenError] = useState<string | null>(null);
  const chatOpenPending = useRef(false);
  const navigationRevision = useRef(0);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { theme, toggle, brand, toggleBrand } = useTheme();
  const page = location.page;
  const mainRef=useRef<HTMLElement>(null);
  useEffect(()=>{mainRef.current?.scrollTo({top:0});},[page,location.params.task]);
  useEffect(() => {
    const desktop = window.matchMedia('(min-width: 1024px)');
    const closeOnDesktop = () => { if (desktop.matches) setSidebarOpen(false); };
    desktop.addEventListener('change', closeOnDesktop);
    return () => desktop.removeEventListener('change', closeOnDesktop);
  }, []);


  // 统一导航入口：接受顶层页面字符串，或带 Library 内层深链参数的位置对象。
  // sameLocation 挡掉与当前位置相同的目标，避免重复 setState 与 hash 抖动。
  const navigate = useCallback((target: NavLocation | string) => {
    navigationRevision.current += 1;
    const next: NavLocation =
      typeof target === "string" ? { page: normalizePage(target), params: {} } : target;
    const conversation = next.page === 'chat' ? Number(next.params.conversation) : 0;
    if (Number.isSafeInteger(conversation) && conversation > 0) setActiveConv(conversation);
    setLocation((prev) => (sameLocation(prev, next) ? prev : next));
  }, []);

  const selectConversation = useCallback((id: number | null) => {
    setActiveConv(id);
    setLocation(prev => {
      if (prev.page !== 'chat') return prev;
      const params = { ...prev.params };
      if (id === null) delete params.conversation;
      else params.conversation = String(id);
      return { ...prev, params };
    });
  }, []);

  // Library 内层状态变化时只更新参数，不重置页面。
  const updateLibraryParams = useCallback((params: Record<string, string>) => {
    setLocation((prev) => {
      const next = { page: "library", params };
      return sameLocation(prev, next) ? prev : next;
    });
  }, []);

  // Cross-page "open this paper" — e.g. clicking a RAG source chip in Chat.
  const openPaper = useCallback(
    (id: number) => {
      setOpenPaperId(id);
      navigate("library");
    },
    [navigate],
  );
  const clearOpenPaper = useCallback(() => setOpenPaperId(null), []);
  const guide = useGettingStarted(navigate,openPaper);

  // Explicit paper entry starts its own conversation. Materials belong to that
  // conversation ID, never to the global chat page or the next blank chat.
  const askAboutPaper = useCallback(
    async (paperId: number, paperTitle: string | null, selectedText?: string) => {
      if (chatOpenPending.current) return;
      chatOpenPending.current = true;
      setChatOpenError(null);
      const revision = navigationRevision.current;
      try {
        const conversation = await api.createConversation(paperId);
        if (navigationRevision.current !== revision) return;
        storeChatContext(conversation.id,{ paperId, paperTitle, selectedText: selectedText ?? null });
        setActiveConv(conversation.id);
        navigate("chat");
      } catch (error: any) {
        if (navigationRevision.current === revision) setChatOpenError(error?.message ?? '无法创建论文对话，请重试。');
      } finally {
        chatOpenPending.current = false;
      }
    },
    [navigate,api,storeChatContext],
  );
  const restoreChatPaperContext = useCallback((id: number, context: PaperChatContext | null) => {
    const saved=readConversationContext(localStore(),libraryScope(),workspace.id,id);
    storeChatContext(id,restoreConversationContext(saved,context));
  }, [workspace.id,storeChatContext]);
  const discussPapers = useCallback(async (papers: {id: number; title: string | null}[]) => {
    if (!papers.length || chatOpenPending.current) return;
    chatOpenPending.current = true;
    setChatOpenError(null);
    const revision = navigationRevision.current;
    try {
      const conversation = await api.createPaperDiscussion(papers.map(p => p.id));
      if (navigationRevision.current !== revision) return;
      storeChatContext(conversation.id, {paperId: papers[0].id, paperTitle: papers[0].title, selectedText: null, papers});
      setActiveConv(conversation.id);
      navigate('chat');
    } catch (error: any) {
      if (navigationRevision.current === revision) setChatOpenError(error?.message ?? '无法创建论文讨论，请重试。');
    } finally { chatOpenPending.current = false; }
  }, [api, navigate, storeChatContext]);
  const clearChatPaperContext = useCallback(async () => {
    if (activeConv == null) return;
    try {
      await api.clearConversationPaper(activeConv);
      storeChatContext(activeConv,null);
    } catch (error: any) {
      setChatOpenError(error?.message ?? '无法退出论文上下文，请重试。');
    }
  }, [activeConv,api,storeChatContext]);
  const consumeChatSelection = useCallback(() => {
    if (activeConv == null) return;
    const context=chatContexts[activeConv];
    if(context?.selectedText)storeChatContext(activeConv,{...context,selectedText:null});
  }, [activeConv,chatContexts,storeChatContext]);

  // 状态 → hash（replaceState 不触发 hashchange，天然避免更新循环）。
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = { ...location.params };
    if (location.page === 'chat') {
      if (activeConv === null) delete params.conversation;
      else params.conversation = String(activeConv);
    }
    const nextHash = buildHash({ ...location, params });
    if (window.location.hash !== nextHash) {
      window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}${nextHash}`);
    }
  }, [location, activeConv]);

  // hash → 状态（用户手输 URL、前进/后退）。与当前位置相同则不触发。
  useEffect(() => {
    if (typeof window === "undefined") return;
    const syncFromHash = () => {
      navigationRevision.current += 1;
      const next = parseHash(window.location.hash);
      const conversation = next.page === 'chat' ? Number(next.params.conversation) : 0;
      if (Number.isSafeInteger(conversation) && conversation > 0) setActiveConv(conversation);
      setLocation((prev) => (sameLocation(prev, next) ? prev : next));
    };
    window.addEventListener("hashchange", syncFromHash);
    return () => window.removeEventListener("hashchange", syncFromHash);
  }, []);

  useEffect(() => {
    let alive = true;
    api
      .listSuggestions("new")
      .then((s) => alive && setNewCount(s.length))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [page]);

  return (
    <ToastProvider>
    <ConfirmProvider>
    <div className="app-frame flex overflow-hidden"><a href="#main-content" className="skip-link" onClick={e=>{e.preventDefault();mainRef.current?.focus();}}>跳到内容</a>
      <Sidebar page={page} open={sidebarOpen} onClose={()=>setSidebarOpen(false)} onNavigate={navigate} newCount={newCount}/>

      {sidebarOpen && (
        <div
          className="modal-overlay z-30 lg:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      <main id="main-content" tabIndex={-1} ref={mainRef} {...(sidebarOpen ? {inert: ''} : {})} className="app-main flex-1 min-w-0 overflow-auto">
        <header
          className="app-header"
        >
          <div className="flex min-w-0 items-center gap-2">
            <button
              onClick={() => setSidebarOpen(true)}
              className="btn-ghost shrink-0 p-2 lg:hidden"
              aria-label="打开导航"
            >
              <Menu size={18} />
            </button>
            <div className="header-project-location text-sm">
              <span className="header-project-name" title={workspace.name}>{workspace.name} <span aria-hidden="true">/</span></span>
              <span className="header-page-title">{pageLabels[page]}</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="workspace-status"><i/> 本地研究空间</span>
            <button className="brand-toggle" onClick={toggleBrand} aria-label={`切换到${brand==='warm'?'蓝色':'暖色'}品牌`} title={`当前${brand==='warm'?'暖色':'蓝色'}强调，点击切换`}><i aria-hidden="true"/>{brand==='warm'?'暖色':'蓝色'}</button>
            <ThemeToggle theme={theme} toggle={toggle} />
          </div>
        </header>
        {/*
          内容壳只提供纵向 padding；横向 padding + 居中 + 宽度由各页面的 <Shell>
          自治（wide/narrow/fluid）。这样 header 的 px 与各页 Shell 的 px 对齐，
          内容居中、宽度按页面用途区分。
        */}
        <div className={`app-page page-${page}`}>
          {contextStorageError&&<Shell><p role="status" className="text-sm">浏览器暂时无法保存论文摘录，内容保留在当前窗口；关闭窗口前请发送或另行保存。</p></Shell>}
          {page!=='help'&&<Shell><GettingStarted guide={guide} page={page} onHelp={()=>navigate('help')}/></Shell>}
          <Suspense
            fallback={
              <div className="space-y-4">
                <Skeleton variant="card" />
                <SkeletonGroup variant="row" count={4} />
              </div>
            }
          >
            {page === "home" && <Home guided={guide.state?.status==='welcome'||guide.state?.status==='active'} onOpenPaper={openPaper} onNavigate={navigate} />}
            {page === "research" && <Research params={location.params} onNavigate={navigate} onOpenPaper={openPaper} />}
            {page === 'wiki' && <Wiki params={location.params} onNavigate={navigate} onOpenPaper={openPaper}/>}
            {page === "library" && (
              <Library
                openPaperId={openPaperId}
                onConsumedOpen={clearOpenPaper}
                onNavigate={navigate}
                deepParams={location.params}
                onDeepParamsChange={updateLibraryParams}
                onAskAboutPaper={askAboutPaper}
                onDiscussPapers={discussPapers}
              />
            )}
            {page === "suggestions" && <Suggestions onOpenPaper={openPaper} />}
            {page === "ideas" && <Ideas />}
            {page === "graph" && <Graph theme={theme} brand={brand} onOpenPaper={openPaper} />}
            {chatOpenError && <div role="alert" className="p-4 text-sm">{chatOpenError}<button className="btn-ghost ml-2" onClick={() => setChatOpenError(null)}>关闭</button></div>}
            {page === "chat" && (
              <Chat
                key={activeConv ?? 'empty-chat'}
                activeConv={activeConv}
                setActiveConv={selectConversation}
                onOpenPaper={openPaper}
                paperContext={activeConv == null ? null : chatContexts[activeConv] ?? null}
                onClearPaperContext={clearChatPaperContext}
                onContextLoaded={restoreChatPaperContext}
                onSelectionConsumed={consumeChatSelection}
                onConversationDeleted={id => storeChatContext(id,null)}
              />
            )}
            {page === "skills" && <Skills />}
            {page === "settings" && <Settings />}
            {page === 'help' && <Help guide={guide} onNavigate={navigate}/>}
          </Suspense>
        </div>
      </main>
    </div>
    </ConfirmProvider>
    </ToastProvider>
  );
}
