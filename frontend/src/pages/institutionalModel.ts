export const institutionalLabel = (value: string): string => ({
  pending: '等待处理', preparing: '正在准备下载环境', downloading: '正在获取全文',
  waiting_user: '请在浏览器中完成登录或验证', attached: 'PDF 已入库', has_pdf: '已有 PDF',
  waiting_verification: '请在浏览器中完成人机验证', waiting_login: '请在浏览器中完成学校登录',
  verification_required: '人机验证尚未完成，可继续任务',
  no_permission: '当前机构没有本文权限', needs_manual: '请使用浏览器下载模式',
  unverified: '论文身份未确认，已保留文件', invalid_pdf: '未取得有效 PDF',
  identity_changed: '题录已修改，请重新选择', not_found: '论文已删除或不存在',
  import_failed: 'PDF 已下载，入库未完成', needs_attention: '下载未完成，请选择恢复方式',
  environment_failed: '下载环境准备失败', worker_failed: '下载引擎未返回结果',
  completed: '已完成', interrupted: '任务中断，可继续', stopped: '已停止', running: '正在处理', done: '处理结束',
}[value] ?? value);

export function retryPaperIds(results: {paper_id:number; status:string}[]): number[] {
  return results.filter(row => !['attached', 'has_pdf', 'not_found'].includes(row.status)).map(row => row.paper_id);
}
export function downloadSelectionValid(ids: number[], mode: 'auto'|'manual'): boolean {
  return ids.length > 0 && ids.length <= (mode === 'manual' ? 1 : 10);
}
