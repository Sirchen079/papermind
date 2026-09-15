import type { NavLocation } from './navigationModel';

export const GUIDE_KEY = 'getting_started_v1';
export interface GuideState { version: 1; status: 'welcome' | 'active' | 'paused' | 'completed'; step: number; }
export interface Lesson {
  id: string; title: string; purpose: string; instructions: string[]; action: string;
  target: NavLocation; usePaper?: boolean; useResearch?: boolean;
}
export const LESSONS: Lesson[] = [
  { id:'import', title:'导入一篇论文', purpose:'先把手头的一篇论文放进来，不需要先配置 AI。', instructions:['点击“去导入 PDF”，选择本机 PDF 文件。','等导入结果出现，再打开论文。没有 PDF 时，也可以切换到手动录入或 arXiv。'], action:'去导入 PDF', target:{page:'library',params:{import:'pdf'}} },
  { id:'read', title:'阅读并记下一点发现', purpose:'论文库保存原文，也保存你自己的阅读记录。', instructions:['打开论文后，点击“阅读”查看 PDF 原文。','在论文详情切换到“笔记 & 摘录”，写一点发现并点击“添加笔记”。摘录记录原文，笔记记录你的理解。'], action:'打开一篇论文', target:{page:'library',params:{}}, usePaper:true },
  { id:'models', title:'需要 AI 时再配置', purpose:'AI 用来生成摘要和辅助研究；导入、阅读和记笔记可以先做。', instructions:['到设置填写服务商提供的接口地址、接口类型和 API key，点击“添加提供商”。','获取模型列表或手动添加模型，再把所需文本模型设为“对话/总结/抽取”。向量模型用于全文检索，可以稍后配置。'], action:'打开模型设置', target:{page:'settings',params:{}} },
  { id:'research', title:'带着一个问题读论文', purpose:'“论文研究”会把选定论文中与问题相关的内容整理在一起。', instructions:['选 1–5 篇论文，输入一个具体问题，例如“这些论文的方法有什么不同？”。','选“快速了解”得到简短解释，或选“逐篇比较”先整理每篇论文，再点击“开始研究”。这一步会调用你配置的模型。'], action:'试着填写一个问题', target:{page:'research',params:{question:'这些论文的方法有什么不同？'}} },
  { id:'review', title:'核对回答，再保存自己的判断', purpose:'AI 给出的内容是草稿。你需要对照论文，判断这句话有没有依据。', instructions:['在“查看原文依据”中读对应片段，修改“我的研究结论”后点击“保存判断”。','展开“原文能支持这句话吗？”，记录核对结果和原因。修改结论后需重新核对；“采用”只表示你打算使用它。'], action:'去查看研究结果', target:{page:'research',params:{}}, useResearch:true },
  { id:'export', title:'带走结果，或先停在这里', purpose:'把整理好的内容用于组会；需要更多证据时再继续。', instructions:['保存判断后，点击“保存组会素材”，展开生成的材料，再点击“导出 Markdown”。','“保留验证计划”保存下一步建议，不会执行实验。目前不需要继续时，点击“目前足够，留在这里”。'], action:'去整理组会材料', target:{page:'research',params:{}}, useResearch:true },
];
export function parseGuide(raw: string | null | undefined, paperCount: number): GuideState {
  try {
    const value=JSON.parse(raw??'null');
    if(value?.version===1 && ['welcome','active','paused','completed'].includes(value.status) && Number.isInteger(value.step) && value.step>=0 && value.step<LESSONS.length) return value;
  } catch { /* Unknown/old saved formats fall back to the welcome decision. */ }
  return {version:1,status:paperCount===0?'welcome':'paused',step:0};
}
export function nextLesson(state: GuideState): GuideState {
  return state.step===LESSONS.length-1 ? {...state,status:'completed'} : {...state,status:'active',step:state.step+1};
}
