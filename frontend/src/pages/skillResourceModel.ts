// 纯逻辑模型：科研技能库面板（BuiltinSkills）对父页面技能包导入/更新/删除的同步判定。
// 目录与资源仍由 BuiltinSkills 单一拉取（单一数据源），父页面（Skills）只在变更成功后
// 递增 revision 失效信号传入；这里只放组件内会真正调用的判定，不引入第二套数据。

export interface CatalogSkillRef { id: string }
export interface CatalogFamilyRef { skills: CatalogSkillRef[] }

/**
 * 目录重新拉取后仍应保留的当前选择：所选技能已不在目录（包被删除，或工作区
 * 目录不含该 ID）时返回空串，由既有 selected effect 复位资源/文件列表/筛选；
 * 同 ID 包更新后 ID 不变，保留选择并继续刷新其资源文本。
 */
export function nextSelectionAfterCatalogRefresh(selected: string, families: CatalogFamilyRef[]): string {
  if (!selected) return '';
  return families.some((family) => family.skills.some((skill) => skill.id === selected)) ? selected : '';
}

/**
 * 同一技能包更新后的资源刷新路径：保留用户当前打开的文件；该文件已被更新移除
 * 或列表不可用时回退 SKILL.md，避免留下失效路径。
 */
export function refreshResourcePath(currentPath: string, files: string[]): string {
  return files.includes(currentPath) ? currentPath : 'SKILL.md';
}
