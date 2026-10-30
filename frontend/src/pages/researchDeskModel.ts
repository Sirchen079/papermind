type DeskTheme = {id:string;name:string};
type DeskPaper = {paper_id:number;title:string;themes:string[]};
type DeskMap = {themes:DeskTheme[];papers:DeskPaper[];assignments?:Record<string,{themes:string[]}>};

// 首页呈现的是地图的主题归属关系，不将归属误写为引用或证据支撑关系。
export function buildResearchDeskGraph(map:DeskMap|null) {
  const allThemes=map?.themes??[];
  const papers=map?.papers??[];
  const known=new Set(allThemes.map(theme=>theme.id));
  const membership=new Map(papers.map(paper=>[paper.paper_id,[...new Set((map?.assignments?.[String(paper.paper_id)]?.themes??paper.themes).filter(id=>known.has(id)))]]));
  const linked=papers.filter(paper=>membership.get(paper.paper_id)?.length);
  const themes=allThemes.filter(theme=>linked.some(paper=>membership.get(paper.paper_id)?.includes(theme.id))).slice(0,3);
  const chosen=new Map<number,DeskPaper>();
  // 先给每个可见主题一个实际成员，再填充剩余位置。
  for(const theme of themes){const paper=linked.find(item=>membership.get(item.paper_id)?.includes(theme.id));if(paper)chosen.set(paper.paper_id,paper);}
  for(const paper of linked){if(chosen.size>=6)break;if(themes.some(theme=>membership.get(paper.paper_id)?.includes(theme.id)))chosen.set(paper.paper_id,paper);}
  const visible=[...chosen.values()];
  const edges=themes.flatMap(theme=>visible.filter(paper=>membership.get(paper.paper_id)?.includes(theme.id)).map(paper=>({themeId:theme.id,paperId:paper.paper_id})));
  return {themes,papers:visible,edges,totalPaperCount:papers.length,linkedPaperCount:linked.length,hiddenPaperCount:linked.length-visible.length};
}
