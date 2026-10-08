const labels: Record<string, string> = {
  search_library: '正在研究文献', get_paper: '正在了解论文', get_paper_full_text: '正在阅读论文全文',
  search_research_notes: '正在回顾研究笔记', read_paper_notes: '正在读取已保存的论文笔记', search_topic_wiki: '正在查阅专题知识',
  read_review: '正在读取已有研究材料', read_research_task: '正在读取已保存的研究判断', search_paper_text: '正在查找论文原文',
  read_chat_sources: '正在回查先前读取的来源',
  search_saved_documents: '正在查找已保存文档', read_saved_document: '正在读取已有研究文档',
  search_web: '正在搜索网络', read_webpage: '正在阅读网页', read_local_file: '正在读取文件',
  import_paper_pdf: '正在获取论文全文并存入本地',
  prepare_paper_card_sources: '正在整理论文来源与图式清单', audit_paper_card: '正在检查精读卡', read_skill_run: '正在读取技能执行记录',
  save_research_idea: '正在保存研究灵感', save_paper_note: '正在保存论文笔记', save_document: '正在整理研究文档',
  tag_paper: '正在整理论文标签', add_paper_to_collection: '正在归入论文合集',
};
export function agentActivityLabel(phase: string, name?: string, question = '') {
  if (phase === 'tool') return labels[name ?? ''] ?? '正在使用研究工具';
  if (phase === 'review') return '正在核对资料与回答';
  if (phase === 'responding') return '正在整理回答';
  return /idea|头脑风暴|灵感|构思|brainstorm/i.test(question) ? '正在构思研究思路' : '正在思考你的问题';
}
