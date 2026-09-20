const labels: Record<string, string> = {
  search_library: '正在研究文献', get_paper: '正在了解论文', get_paper_full_text: '正在阅读论文全文',
  search_research_notes: '正在回顾研究笔记', search_topic_wiki: '正在查阅专题知识',
  search_web: '正在搜索网络', read_webpage: '正在阅读网页', read_local_file: '正在读取文件',
  save_research_idea: '正在保存研究灵感', save_paper_note: '正在保存论文笔记', save_document: '正在整理研究文档',
  tag_paper: '正在整理论文标签', add_paper_to_collection: '正在归入论文合集',
};
export function agentActivityLabel(phase: string, name?: string, question = '') {
  if (phase === 'tool') return labels[name ?? ''] ?? '正在使用研究工具';
  if (phase === 'review') return '正在核对资料与回答';
  if (phase === 'responding') return '正在整理回答';
  return /idea|头脑风暴|灵感|构思|brainstorm/i.test(question) ? '正在构思研究思路' : '正在思考你的问题';
}
