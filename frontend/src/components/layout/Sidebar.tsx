import { useEffect, useRef, useState } from 'react';
import { WorkspaceMenu } from '../WorkspaceMenu';
import { Blocks, BookOpen, Inbox, Lightbulb, Logo, Menu, MessageSquare, Settings, Share2, Sparkles } from '../../icons';

const primary = [
  {key:'home',label:'研究主页',icon:Inbox,hint:'从这里开始或继续上次工作'},
  {key:'library',label:'论文库',icon:BookOpen,hint:'导入、阅读、记笔记'},
  {key:'research',label:'论文研究',icon:Sparkles,hint:'围绕问题整理与比较论文'},
  {key:'chat',label:'论文问答',icon:MessageSquare,hint:'提问或解释一段内容'},
];
const more = [
  {key:'wiki',label:'专题知识',icon:BookOpen,hint:'积累专题判断、证据与修订记录'},
  {key:'suggestions',label:'研究建议',icon:Lightbulb,hint:'查看新论文与相关线索'},
  {key:'ideas',label:'研究想法',icon:Sparkles,hint:'记录和整理研究点子'},
  {key:'graph',label:'关系图谱',icon:Share2,hint:'探索论文与概念的联系'},
  {key:'skills',label:'自定义技能',icon:Blocks,hint:'复用自定义 AI 处理方式'},
];
export const pageLabels:Record<string,string> = Object.fromEntries([...primary,...more,{key:'help',label:'使用指南'},{key:'settings',label:'设置'}].map(item=>[item.key,item.label]));

export function Sidebar({page,open,onClose,onNavigate,newCount}:{page:string;open:boolean;onClose:()=>void;onNavigate:(page:string)=>void;newCount:number}) {
  const [collapsed,setCollapsed]=useState(()=>{try{return localStorage.getItem('pm-sidebar-collapsed')==='true';}catch{return false;}});
  const panel = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.querySelector<HTMLButtonElement>('.sidebar-close')?.focus();
    function keydown(event: KeyboardEvent) {
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
  function toggle(){setCollapsed(value=>{try{localStorage.setItem('pm-sidebar-collapsed',String(!value));}catch{/* optional preference */}return !value;});}
  function go(key:string){onNavigate(key);onClose();}
  function itemButton(item:typeof primary[number]) {
    const Icon=item.icon;
    return <button key={item.key} className="nav-link" aria-label={item.label} aria-current={page===item.key?'page':undefined} title={`${item.label} · ${item.hint}`} onClick={()=>go(item.key)}>
      <Icon size={18}/><span className="sidebar-copy flex-1">{item.label}</span>
      {item.key==='suggestions'&&newCount>0&&<span className="sidebar-copy text-xs">{newCount}</span>}
    </button>;
  }
  return <aside ref={panel} aria-label="工作区导航" role={open?'dialog':undefined} aria-modal={open?true:undefined} className={`app-sidebar ${collapsed?'is-collapsed':''} ${open?'is-open':''}`}>
    <div className="sidebar-brand"><span className="brand-symbol"><Logo size={25}/></span><span className="sidebar-copy brand-name">PaperMind</span><button className="btn-subtle sidebar-close lg:hidden" aria-label="关闭导航" onClick={onClose}>×</button></div>
    <WorkspaceMenu/>
    <button className="sidebar-new" onClick={()=>go('research')} title="开始新的论文研究" aria-label="开始新的论文研究"><span aria-hidden="true" className="text-xl leading-none">+</span><span className="sidebar-copy">新研究</span></button>
    <p className="sidebar-copy nav-section-label">日常研究</p>
    <nav aria-label="主导航" className="space-y-1">{primary.map(itemButton)}</nav>
    <div className="sidebar-tools">
      <p className="sidebar-copy nav-section-label">探索与积累</p>
      <nav aria-label="更多工具" className="space-y-1">{more.map(itemButton)}</nav>
    </div>
    <div className="sidebar-footer">
      <button className="nav-link" aria-label="使用指南" aria-current={page==='help'?'page':undefined} title="使用指南" onClick={()=>go('help')}><BookOpen size={17}/><span className="sidebar-copy">使用指南</span></button>
      <button className="nav-link" aria-label="设置" aria-current={page==='settings'?'page':undefined} title="设置" onClick={()=>go('settings')}><Settings size={17}/><span className="sidebar-copy">设置</span></button>
      <div className="sidebar-bottom"><span className="sidebar-copy text-xs text-faint">你的本地研究空间</span><button className="btn-subtle hidden lg:inline-flex p-2" aria-label={collapsed?'展开侧栏':'收起侧栏'} title={collapsed?'展开侧栏':'收起侧栏'} onClick={toggle}><Menu size={17}/></button></div>
    </div>
  </aside>;
}
