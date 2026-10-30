import { useEffect, useRef } from 'react';
import { Blocks, BookOpen, Inbox, Lightbulb, Logo, MessageSquare, Search, Settings, Share2, Sparkles } from '../../icons';

const primary = [
  {key:'home',label:'研究主页',icon:Inbox,hint:'从这里开始或继续上次工作'},
  {key:'library',label:'论文库',icon:BookOpen,hint:'导入、阅读、记笔记'},
  {key:'chat',label:'研究对话',icon:MessageSquare,hint:'持续补查、比较、讨论与修订'},
  {key:'research',label:'论文整理',icon:Sparkles,hint:'快速比较少量论文，或批量整理专题综述'},
  {key:'cards',label:'精读卡片',icon:BookOpen,hint:'按专题浏览精读卡片，可单篇导出'},
  {key:'map',label:'文献地图',icon:Share2,hint:'研究主题、值得研究的问题与阅读路线'},
];
const more = [
  {key:'literature',label:'文献调研',icon:Search,hint:'让 AI 检索公开文献，勾选后加入论文库'},
  {key:'wiki',label:'专题知识',icon:BookOpen,hint:'积累专题判断、证据与修订记录'},
  {key:'suggestions',label:'研究建议',icon:Lightbulb,hint:'查看新论文与相关线索'},
  {key:'ideas',label:'研究想法',icon:Sparkles,hint:'记录和整理研究点子'},
  {key:'graph',label:'关系图谱',icon:Share2,hint:'探索论文与概念的联系'},
  {key:'skills',label:'自定义技能',icon:Blocks,hint:'复用自定义 AI 处理方式'},
];
export const pageLabels:Record<string,string> = Object.fromEntries([...primary,...more,{key:'help',label:'使用指南'},{key:'settings',label:'设置'}].map(item=>[item.key,item.label]));

export function Sidebar({page,open,onClose,onNavigate,onNewResearch,newCount}:{page:string;open:boolean;onClose:()=>void;onNavigate:(page:string)=>void;onNewResearch:()=>void;newCount:number}) {
  const toolsDialog=useRef<HTMLDialogElement>(null);
  const panel = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.querySelector<HTMLButtonElement>('.sidebar-close')?.focus();
    function keydown(event: KeyboardEvent) {
      if (toolsDialog.current?.open) return;
      if (event.key === 'Escape') { event.preventDefault(); closeRef.current(); }
      if (event.key !== 'Tab') return;
      const controls = Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled), [href]') ?? []).filter(el => el.getClientRects().length);
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    document.addEventListener('keydown', keydown);
    return () => { document.removeEventListener('keydown', keydown); previous?.focus(); };
  }, [open]);
  function go(key:string){toolsDialog.current?.close();onNavigate(key);onClose();}
  function itemButton(item:typeof primary[number]) {
    const Icon=item.icon;
    const short:Record<string,string>={home:'主页',library:'论文',chat:'对话',research:'整理',cards:'精读',map:'地图'};
    return <button key={item.key} className="rail-link" aria-label={item.label} aria-current={page===item.key?'page':undefined} title={`${item.label} · ${item.hint}`} onClick={()=>go(item.key)}>
      <Icon size={21}/><span>{short[item.key]||item.label}</span>
      {item.key==='suggestions'&&newCount>0&&<small>{newCount}</small>}
    </button>;
  }
  return <aside ref={panel} aria-label="工作区导航" role={open?'dialog':undefined} aria-modal={open?true:undefined} className={`app-sidebar navigation-rail ${open?'is-open':''}`}>
    <button className="rail-brand" aria-label="PaperMind 研究主页" title="PaperMind" onClick={()=>go('home')}><Logo size={44}/></button>
    <button className="btn-subtle sidebar-close lg:hidden" aria-label="关闭导航" onClick={onClose}>×</button>
    <button className="rail-create" onClick={()=>{onNewResearch();onClose();}} title="开始新的研究对话" aria-label="开始新的研究对话">+</button>
    <nav aria-label="主导航" className="rail-primary">{primary.map(itemButton)}</nav>
    <button className="rail-link" aria-label="更多研究工具" aria-haspopup="dialog" aria-current={more.some(item=>item.key===page)?'page':undefined} onClick={()=>toolsDialog.current?.showModal()}><Blocks size={21}/><span>工具</span>{newCount>0&&<i className="rail-dot"/>}</button>
    <div className="rail-footer">
      <button className="rail-link" aria-label="使用指南" aria-current={page==='help'?'page':undefined} title="使用指南" onClick={()=>go('help')}><BookOpen size={19}/></button>
      <button className="rail-link" aria-label="设置" aria-current={page==='settings'?'page':undefined} title="设置" onClick={()=>go('settings')}><Settings size={19}/></button>
    </div>
    <dialog ref={toolsDialog} className="workspace-dialog rail-tools-dialog" aria-labelledby="research-tools-title">
      <header><div><p className="workspace-kicker">PAPERMIND</p><h2 id="research-tools-title">探索与积累</h2></div><button className="btn-subtle" aria-label="关闭研究工具" onClick={()=>toolsDialog.current?.close()}>×</button></header>
      <nav aria-label="更多工具">{more.map(itemButton)}</nav>
    </dialog>
  </aside>;
}
