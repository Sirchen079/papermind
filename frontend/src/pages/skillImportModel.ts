// 纯逻辑模型：技能包导入的 GitHub 地址校验、来源类型判断、revision 简写与可否更新。
// 不导入 React 或 api 等运行时模块，保持可被 tsconfig.graph-test.json 单独编译。

export type ImportSourceKind = 'github' | 'folder' | 'zip';

const GITHUB_PREFIX = 'https://github.com/';

/** GitHub 地址需形如 https://github.com/<owner>/<repo>[/tree/<ref>/<path>]；合法返回 null，否则返回中文提示。 */
export function githubUrlError(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return '请填写 GitHub 地址';
  if (!trimmed.toLowerCase().startsWith(GITHUB_PREFIX)) {
    return '请使用 https://github.com/<owner>/<repo> 形式的地址';
  }
  const rest = trimmed.slice(GITHUB_PREFIX.length).replace(/[?#].*$/, '').replace(/\/+$/, '');
  if (/\s/.test(rest)) return '地址中不能包含空格';
  const parts = rest.split('/');
  if (parts.length < 2 || !parts[0] || !parts[1]) return '地址里缺少 owner 或 repo 名';
  if (parts.length > 2 && (parts[2] !== 'tree' || !parts[3])) {
    return '子目录请写成 /tree/<分支>/<目录> 形式';
  }
  return null;
}

/** 按后端返回的 source 字符串判断来源：GitHub 地址 / 本机文件夹路径 / 'zip:<文件名>'。 */
export function sourceKind(source: string): ImportSourceKind {
  const trimmed = source.trim();
  if (trimmed.toLowerCase().startsWith('zip:')) return 'zip';
  if (/^https?:\/\/(www\.)?github\.com(\/|$)/i.test(trimmed)) return 'github';
  return 'folder';
}

/** GitHub 来源可点开的原始地址；其它来源返回 null。 */
export function githubSourceUrl(source: string): string | null {
  const trimmed = source.trim();
  if (sourceKind(trimmed) !== 'github') return null;
  const rest = trimmed.replace(/^https?:\/\/(www\.)?github\.com\/?/i, '').replace(/[?#].*$/, '').replace(/\/+$/, '');
  const parts = rest.split('/');
  return parts.length >= 2 && parts[0] && parts[1] ? trimmed : null;
}

/** zip 包没有可复现的来源，不能重新拉取；GitHub 与文件夹来源可以更新。 */
export function canUpdate(source: string): boolean {
  const trimmed = source.trim();
  if (!trimmed) return false;
  return sourceKind(trimmed) !== 'zip';
}

/** commit sha 等长 revision 显示前 7 位；短版本号原样返回。 */
export function shortRevision(revision: string): string {
  const trimmed = revision.trim();
  return trimmed.length > 7 ? trimmed.slice(0, 7) : trimmed;
}
