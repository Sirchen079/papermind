import { useApi } from '../workspaceContext';
import { useEffect, useMemo, useRef, useState } from 'react';
import cytoscape, { type Core, type NodeSingular } from 'cytoscape';
import { type GraphData } from '../api';
import type { Brand, Theme } from '../theme';
import { CLAIM_EDGE_LABELS, CLAIM_KIND_LABELS, CLAIM_RELATION_ALL, CLAIM_SOURCE_LABELS, CONCEPT_TYPE_LABELS, LEGEND_TYPES, type GraphMode, claimEdgeColor, conceptColor, graphLabel, modeHint, modeLabel, nodeMetrics, nodeTypeLabel, nodeVisualStyle, normalizeNodes, readGraphParams, writeGraphParams } from './graphModel';
import { Shell } from '../components/layout/Shell';
import { EmptyState } from '../components/ui/EmptyState';
import { ResearchMotif } from '../components/ui/ResearchMotif';
import { BookOpen, Share2 } from '../icons';

function fitGraph(cy:Core,readable=false) {
  if(cy.nodes().empty())return;
  cy.fit(undefined,48);
  if(readable&&cy.zoom()<.72){cy.zoom(.72);cy.center();}
  if(cy.zoom()>1){cy.zoom(1);cy.center();}
}
function graphLayout(cy:Core) {
  if(cy.nodes().length<=6||cy.edges().empty())return {name:'grid',fit:false,avoidOverlap:true,avoidOverlapPadding:40,cols:Math.max(1,Math.min(3,Math.floor(cy.width()/250))),spacingFactor:1.12} as const;
  return {name:'breadthfirst',fit:false,animate:false,directed:false,circle:false,grid:false,avoidOverlap:true,nodeDimensionsIncludeLabels:true,spacingFactor:1.05} as const;
}
function applyEmphasis(cy:Core,id:number|null,query:string) {
  cy.elements().removeClass('dimmed focus neighbor');
  const selected=id==null?cy.collection():cy.$id(String(id));
  if(selected.nonempty()){
    const neighborhood=selected.closedNeighborhood();
    cy.elements().not(neighborhood).addClass('dimmed');
    selected.addClass('focus');neighborhood.edges().addClass('neighbor');
  }
  const q=query.trim().toLowerCase();
  if(q){
    const matches=cy.nodes().filter(node=>String(node.data('searchLabel')).toLowerCase().includes(q));
    cy.nodes().not(matches).addClass('dimmed');matches.removeClass('dimmed').addClass('focus');
    matches.connectedEdges().removeClass('dimmed').addClass('neighbor');
    selected.removeClass('dimmed');
  }
}

export default function Graph({theme,brand,onOpenPaper}:{theme:Theme;brand:Brand;onOpenPaper:(id:number)=>void}) {
  const api = useApi();
  const initial=useMemo(()=>readGraphParams(),[]);
  const [mode,setMode]=useState<GraphMode>(initial.mode),[minPapers,setMinPapers]=useState(initial.minPapers);
  const [showCitations,setShowCitations]=useState(true),[claimTypes,setClaimTypes]=useState<string[]>([...CLAIM_RELATION_ALL]);
  const [data,setData]=useState<GraphData|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState('');
  const [reload,setReload]=useState(0),[query,setQuery]=useState(''),[selectedId,setSelectedId]=useState<number|null>(null);
  const [zoom,setZoom]=useState(100),[listLimit,setListLimit]=useState(8);
  const container=useRef<HTMLDivElement>(null),cyRef=useRef<Core|null>(null);
  const focusRef=useRef({id:selectedId,query});focusRef.current={id:selectedId,query};
  const viewRef=useRef<{data:GraphData;positions:Map<string,{x:number;y:number}>;zoom:number;pan:{x:number;y:number}}|null>(null);
  const nodes=useMemo(()=>normalizeNodes(data),[data]);
  const index=useMemo(()=>new Map(nodes.map(node=>[node.id,node])),[nodes]);
  const selected=selectedId==null?null:index.get(selectedId)??null;
  const matching=useMemo(()=>nodes.filter(node=>`${node.label} ${node.paperTitle??''} ${node.text??''}`.toLowerCase().includes(query.trim().toLowerCase())).sort((a,b)=>b.count-a.count),[nodes,query]);
  const related=useMemo(()=>selected?(data?.edges??[]).filter(edge=>edge.source===selected.id||edge.target===selected.id).map(edge=>({edge,node:index.get(edge.source===selected.id?edge.target:edge.source)})).filter(item=>item.node):[],[data,index,selected]);
  const citationIn=selected?(data?.edges??[]).filter(e=>e.edge_type==='citation'&&e.target===selected.id).length:0;
  const citationOut=selected?(data?.edges??[]).filter(e=>e.edge_type==='citation'&&e.source===selected.id).length:0;

  function switchMode(next:GraphMode){setMode(next);setQuery('');setSelectedId(null);setListLimit(8);}
  useEffect(()=>{
    let alive=true;setLoading(true);setError('');setData(null);setSelectedId(null);
    api.graph(mode,minPapers,mode==='paper'?['concept',...(showCitations?['citation']:[])]:undefined,mode==='claims'?claimTypes:undefined)
      .then(next=>{if(alive)setData(mode==='claims'?{...next,edges:next.edges.filter(edge=>claimTypes.includes(edge.edge_type??''))}:next);}).catch(e=>{if(alive)setError(e.message);}).finally(()=>{if(alive)setLoading(false);});
    return()=>{alive=false;};
  },[mode,minPapers,showCitations,claimTypes,reload]);
  useEffect(()=>{writeGraphParams(mode,minPapers);},[mode,minPapers]);
  useEffect(()=>{
    const sync=()=>{const next=readGraphParams();setMode(next.mode);setMinPapers(next.minPapers);setQuery('');setSelectedId(null);};
    window.addEventListener('hashchange',sync);return()=>window.removeEventListener('hashchange',sync);
  },[]);
  useEffect(()=>{
    if(!data||!container.current)return;
    const tokens=getComputedStyle(document.documentElement);
    const color=(name:string)=>tokens.getPropertyValue(name).trim();
    const visual={...nodeVisualStyle(mode,theme,null),focusColor:color('--color-primary')},reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const nodeStyle=(type:string)=>mode==='concept'?nodeVisualStyle(mode,theme,type):{backgroundColor:color('--color-surface'),borderColor:color('--color-border-hover'),textColor:color('--color-text')};
    const edgeColor=(edge:any)=>edge.data('edgeType')==='citation'?(theme==='dark'?'#aa9ac9':'#8e7ca8'):edge.data('edgeType')==='hierarchy'?'#739485':mode==='claims'?claimEdgeColor(edge.data('edgeType')):(theme==='dark'?'#687d7a':'#b7c4c1');
    const restored=viewRef.current?.data===data?viewRef.current:null;
    const cy=cytoscape({container:container.current,layout:{name:'preset'},minZoom:.15,maxZoom:2.6,wheelSensitivity:.22,boxSelectionEnabled:false,
      elements:[...nodes.map((node,i)=>({data:{id:String(node.id),label:graphLabel(node.label,mode),searchLabel:`${node.label} ${node.paperTitle??''} ${node.text??''}`,rawLabel:node.label,type:node.type,count:node.count},position:restored?.positions.get(String(node.id))??{x:Math.cos(i*2*Math.PI/Math.max(1,nodes.length))*320,y:Math.sin(i*2*Math.PI/Math.max(1,nodes.length))*260}})),...data.edges.map((edge,i)=>({data:{id:`edge-${i}`,source:String(edge.source),target:String(edge.target),weight:edge.weight,edgeType:edge.edge_type??'cooccurrence'}}))],
      style:[{selector:'node',style:{label:'data(label)',shape:'round-rectangle','font-family':'Segoe UI, Microsoft YaHei, sans-serif','font-size':14,'font-weight':500,'line-height':1.45,'text-valign':'center','text-halign':'center','text-wrap':'wrap','text-max-width':(e:NodeSingular)=>nodeMetrics(e.data('rawLabel'),e.data('count'),mode).textMaxWidth+'px',width:(e:NodeSingular)=>nodeMetrics(e.data('rawLabel'),e.data('count'),mode).width,height:(e:NodeSingular)=>nodeMetrics(e.data('rawLabel'),e.data('count'),mode).height,padding:'8px','background-color':(e:NodeSingular)=>nodeStyle(e.data('type')).backgroundColor,'border-color':(e:NodeSingular)=>nodeStyle(e.data('type')).borderColor,color:(e:NodeSingular)=>nodeStyle(e.data('type')).textColor,'border-width':1.2,'overlay-opacity':0,'min-zoomed-font-size':5,'text-outline-width':0}},
        {selector:'node.focus',style:{'border-color':visual.focusColor,'border-width':2.5,'background-color':color('--color-inset')}},
        {selector:'node.hover',style:{'border-width':2.3,'border-color':visual.focusColor}},
        {selector:'node.dimmed',style:{opacity:.24}},
        {selector:'edge',style:{width:(e:any)=>Math.min(3,1+Math.sqrt(Math.max(0,e.data('weight')||1))*.38),'line-color':edgeColor,'target-arrow-color':edgeColor,'curve-style':'bezier','control-point-step-size':55,'line-style':(e:any)=>e.data('edgeType')==='hierarchy'?'dashed':'solid','target-arrow-shape':(e:any)=>['citation','hierarchy','supports','contradicts','extends'].includes(e.data('edgeType'))?'triangle':'none','arrow-scale':.75,opacity:.65,'line-cap':'round'}},
        {selector:'edge.neighbor',style:{opacity:1,width:2.4}},
        {selector:'edge.dimmed',style:{opacity:.12}},
      ]});
    cyRef.current=cy;
    cy.on('zoom',()=>setZoom(Math.round(cy.zoom()*100)));
    cy.on('tap','node',event=>setSelectedId(Number(event.target.id())));
    cy.on('tap',event=>{if(event.target===cy)setSelectedId(null);});
    cy.on('mouseover','node',event=>{event.target.addClass('hover');if(container.current)container.current.style.cursor='pointer';});
    cy.on('mouseout','node',event=>{event.target.removeClass('hover');if(container.current)container.current.style.cursor='grab';});
    if(restored){cy.zoom(restored.zoom);cy.pan(restored.pan);}
    else {cy.layout(graphLayout(cy)).run();fitGraph(cy,true);}
    setZoom(Math.round(cy.zoom()*100));applyEmphasis(cy,focusRef.current.id,focusRef.current.query);
    if(!reduced)container.current.animate([{opacity:.4},{opacity:1}],{duration:350});
    let frame=0;
    let lastWidth=container.current.clientWidth,lastHeight=container.current.clientHeight;
    const observer=new ResizeObserver(entries=>{const {width,height}=entries[0].contentRect;if(Math.abs(width-lastWidth)<1&&Math.abs(height-lastHeight)<1)return;lastWidth=width;lastHeight=height;cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{if(!cy.destroyed()){cy.resize();fitGraph(cy,true);}});});observer.observe(container.current);
    return()=>{
      observer.disconnect();cancelAnimationFrame(frame);
      viewRef.current={data,positions:new Map(cy.nodes().map(node=>[node.id(),{...node.position()}])),zoom:cy.zoom(),pan:{...cy.pan()}};
      cy.destroy();if(cyRef.current===cy)cyRef.current=null;
    };
  },[data,mode,theme,brand,nodes]);
  useEffect(()=>{if(cyRef.current)applyEmphasis(cyRef.current,selectedId,query);},[selectedId,query]);
  function focusNode(id:number){
    setSelectedId(id);const cy=cyRef.current;if(!cy)return;const node=cy.$id(String(id));if(node.empty())return;
    const level=Math.min(1,Math.max(.65,cy.width()/(node.outerWidth()+90)));
    if(window.matchMedia('(prefers-reduced-motion: reduce)').matches){cy.zoom(level);cy.center(node);}
    else cy.animate({center:{eles:node},zoom:level},{duration:260});
  }
  function changeZoom(factor:number){const cy=cyRef.current;if(cy)cy.zoom({level:Math.max(cy.minZoom(),Math.min(cy.maxZoom(),cy.zoom()*factor)),renderedPosition:{x:cy.width()/2,y:cy.height()/2}});}
  const emptyMessage=mode==='claims'?'导入或添加论文论断后，可以查看支持、矛盾与延伸关系。':mode==='concept'&&minPapers>1?'当前没有概念满足最少论文数筛选。':'导入论文并生成概念后，已识别的关系会出现在这里。';
  const legend=mode==='paper'?[{label:'共享概念',color:'#91a7a3'},{label:'引用 →',color:'#8e7ca8'}]:mode==='claims'?CLAIM_RELATION_ALL.map(key=>({label:CLAIM_EDGE_LABELS[key]+' →',color:claimEdgeColor(key)})):LEGEND_TYPES.map(key=>({label:CONCEPT_TYPE_LABELS[key],color:conceptColor(key)}));

  return <Shell max="wide" className="graph-workbench">
    <header className="graph-page-heading"><div><p className="graph-eyebrow"><Share2 size={15}/> RESEARCH ATLAS</p><h1 className="page-title">让线索，彼此相连。</h1><p className="page-subtitle">从一篇论文或一个概念出发，沿着关系发现下一步。</p></div><span className="graph-page-name">关系图谱</span></header>
    <section className="atlas-shell" aria-label="关系图谱工作区">
      <div className="atlas-toolbar"><div className="atlas-tabs" role="group" aria-label="图谱模式">{(['paper','concept','claims'] as const).map(item=><button key={item} aria-pressed={mode===item} onClick={()=>switchMode(item)}>{modeLabel(item)}</button>)}</div><label className="atlas-search"><span className="sr-only">搜索节点</span><input value={query} onChange={e=>{setQuery(e.target.value);setListLimit(8);}} placeholder="搜索论文、概念或论断"/>{query&&<button aria-label="清空搜索" onClick={()=>setQuery('')}>×</button>}</label></div>
      <div className="atlas-filters"><span>{loading?'正在读取图谱…':`${nodes.length} 个节点 · ${data?.edges.length??0} 条关系`}</span><div>
        {mode==='paper'&&<label><input type="checkbox" checked={showCitations} onChange={e=>setShowCitations(e.target.checked)}/>显示引用关系</label>}
        {mode==='concept'&&<label>最少论文数 <input aria-label="最少论文数" type="number" min={1} max={100000} value={minPapers} onChange={e=>setMinPapers(Math.max(1,Math.min(100000,Number(e.target.value)||1)))}/></label>}
        {mode==='claims'&&<div role="group" aria-label="论断关系类型过滤">{CLAIM_RELATION_ALL.map(type=><button key={type} aria-pressed={claimTypes.includes(type)} onClick={()=>setClaimTypes(types=>types.includes(type)?types.filter(t=>t!==type):[...types,type])}><i style={{background:claimEdgeColor(type)}}/>{CLAIM_EDGE_LABELS[type]}</button>)}</div>}
      </div></div>
      {error&&<div role="alert" className="atlas-error">图谱加载失败：{error}<button className="btn-ghost" onClick={()=>setReload(n=>n+1)}>重试</button></div>}
      <div className="atlas-body"><div className="atlas-map-wrap">
        <div ref={container} className="atlas-map" aria-label="可拖动缩放的关系画布"/>
        {loading&&<div className="atlas-overlay" role="status">正在连接已有线索…</div>}
        {!loading&&!error&&nodes.length===0&&<div className="atlas-overlay"><EmptyState icon={<Share2 size={24}/>} title="暂无可展示节点" hint={emptyMessage} action={mode==='concept'&&minPapers>1?<button className="btn-primary" onClick={()=>setMinPapers(1)}>显示全部概念</button>:undefined}/></div>}
        {!loading&&nodes.length>0&&data?.edges.length===0&&<p className="atlas-map-note">当前没有连线，节点独立显示。</p>}
        <div className="atlas-map-caption" aria-hidden="true"><span>拖动探索 · 滚轮缩放</span><span>{mode==='paper'?'LITERATURE':mode==='concept'?'CONCEPTS':'CLAIMS'}</span></div>
        <div className="atlas-zoom" aria-label="画布控制"><button aria-label="缩小图谱" disabled={!nodes.length} onClick={()=>changeZoom(1/1.2)}>−</button><output aria-label="图谱缩放比例">{zoom}%</output><button aria-label="放大图谱" disabled={!nodes.length} onClick={()=>changeZoom(1.2)}>+</button><button disabled={!nodes.length} onClick={()=>{if(cyRef.current)fitGraph(cyRef.current);}}>适配</button><button disabled={!nodes.length} onClick={()=>{const cy=cyRef.current;if(cy){cy.layout(graphLayout(cy)).run();fitGraph(cy);}}}>重排</button></div>
      </div><aside className="atlas-inspector" aria-label="节点与关系详情">
        <div className="atlas-inspector-heading"><span>{selected?'当前线索':'从一个节点开始'}</span>{selected&&<button onClick={()=>setSelectedId(null)}>清除选中</button>}</div>
        {selected?<div className="atlas-selection" key={`${mode}-${selected.id}`}>
          <p className="atlas-kicker">{mode==='paper'?'论文':mode==='concept'?nodeTypeLabel(selected.type)||'概念':CLAIM_KIND_LABELS[selected.type??'']||'论断'}{selected.year?` · ${selected.year}`:''}</p>
          <h2>{selected.label}</h2>
          {mode==='claims'&&<><p className="atlas-meta">{CLAIM_SOURCE_LABELS[selected.source??'']??selected.source}{selected.paperTitle?` · ${selected.paperTitle}`:''}</p>{selected.text&&<p className="atlas-claim-text">{selected.text}</p>}</>}
          {mode==='paper'&&<p className="atlas-meta">引用库内 {citationOut} 篇 · 被库内 {citationIn} 篇引用</p>}
          {mode==='concept'&&<p className="atlas-meta">出现在 {selected.count} 篇论文中</p>}
          {(mode==='paper'||mode==='claims'&&selected.paperId!=null)&&<button className="btn-primary atlas-open" onClick={()=>onOpenPaper(mode==='paper'?selected.id:selected.paperId!)}><BookOpen size={14}/>{mode==='paper'?'在库中打开':'打开所属论文'}<span aria-hidden="true">↗</span></button>}
          <div className="atlas-neighbors"><h3>相邻关系 <span>{related.length}</span></h3>{related.length===0?<p className="atlas-meta">当前图谱中还没有与它相连的节点。</p>:related.map(({edge,node},i)=><button key={i} onClick={()=>focusNode(node!.id)}><span>{node!.label}</span><small>{edge.edge_type==='citation'?(edge.source===selected.id?'引用 →':'被引用 ←'):edge.edge_type==='hierarchy'?'上下位关系':CLAIM_EDGE_LABELS[edge.edge_type??'']?`${CLAIM_EDGE_LABELS[edge.edge_type!]} ${edge.source===selected.id?'→':'←'}`:`共享${mode==='paper'?'概念':'论文'} · ${edge.weight}`}</small></button>)}</div>
        </div>:<div className="atlas-invitation"><ResearchMotif icon={<Share2 size={23}/>}/><h2>顺着联系，展开思路。</h2><p>点击画布或下方列表中的节点，查看完整内容与相邻关系。</p></div>}
        <section className="atlas-node-list"><h3>{query?'搜索结果':'浏览节点'} <span>{matching.length}</span></h3>{matching.slice(0,listLimit).map(node=><button key={node.id} aria-pressed={selectedId===node.id} onClick={()=>focusNode(node.id)}><i style={{background:mode==='concept'?conceptColor(node.type):'var(--accent)'}}/><span>{node.label}</span><span aria-hidden="true">↗</span></button>)}{!matching.length&&<p className="atlas-meta">{query?'没有匹配的节点，换个关键词试试。':'节点会随已有材料出现在这里。'}</p>}{matching.length>listLimit&&<button className="atlas-show-more" onClick={()=>setListLimit(n=>n+20)}>显示更多节点</button>}</section>
      </aside></div>
      <footer className="atlas-legend"><div>{legend.map(item=><span key={item.label}><i style={{background:item.color}}/>{item.label}</span>)}</div><details><summary>如何读图</summary><p>{modeHint(mode)} {mode==='concept'?'虚线箭头表示上下位关系。':mode==='paper'?'箭头从引用方指向被引用论文。':'箭头表示关系方向。'} 节点尺寸优先适应标题长度，不表示重要性。</p></details></footer>
    </section>
  </Shell>;
}
