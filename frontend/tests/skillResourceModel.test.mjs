import assert from "node:assert/strict";
import { test } from "node:test";

import {
  nextSelectionAfterCatalogRefresh,
  refreshResourcePath,
} from "../.tmp_graph_test_dist/skillResourceModel.js";

// R08 回归：技能包导入/更新/删除后，科研技能库面板的目录失效与当前选择、
// 已打开资源的同步判定。目录/资源仍由 BuiltinSkills 单一拉取，父页面只在
// 变更成功后递增 revision 失效信号；这里覆盖组件内会真正调用的两个判定。

const fam = (id, slugs) => ({ id, skills: slugs.map((s) => ({ id: `${id}/${s}` })) });
const catalog = [fam("import-demo-pack", ["demo"]), fam("import-other", ["helper"])];

test("同 ID 包更新后目录刷新，已选技能仍存在时保留选择", () => {
  assert.equal(nextSelectionAfterCatalogRefresh("import-demo-pack/demo", catalog), "import-demo-pack/demo");
  assert.equal(nextSelectionAfterCatalogRefresh("import-other/helper", catalog), "import-other/helper");
});

test("所选技能所属包被删除后，目录刷新清空该选择", () => {
  assert.equal(nextSelectionAfterCatalogRefresh("import-demo-pack/demo", [catalog[1]]), "");
  assert.equal(nextSelectionAfterCatalogRefresh("import-demo-pack/demo", []), "");
});

test("未选择技能时目录刷新保持为空，不产生选择", () => {
  assert.equal(nextSelectionAfterCatalogRefresh("", catalog), "");
});

test("按技能 ID 精确匹配：相似 ID 或其他技能存在不误保留", () => {
  assert.equal(nextSelectionAfterCatalogRefresh("import-demo-pack/other-skill", catalog), "");
  assert.equal(nextSelectionAfterCatalogRefresh("import-demo-packs/demo", catalog), "");
  assert.equal(nextSelectionAfterCatalogRefresh("import-demo-pack/demo/", catalog), "");
});

test("同 ID 包更新后刷新已打开资源：文件仍在列表时保留当前路径", () => {
  assert.equal(refreshResourcePath("SKILL.md", ["SKILL.md", "references/apa.md"]), "SKILL.md");
  assert.equal(refreshResourcePath("references/apa.md", ["SKILL.md", "references/apa.md"]), "references/apa.md");
});

test("更新把已打开文件移除后回退 SKILL.md，不留下失效路径", () => {
  assert.equal(refreshResourcePath("references/old.md", ["SKILL.md", "references/new.md"]), "SKILL.md");
});

test("文件列表为空时仍回退 SKILL.md，资源请求发出前路径始终有效", () => {
  assert.equal(refreshResourcePath("SKILL.md", []), "SKILL.md");
  assert.equal(refreshResourcePath("references/apa.md", []), "SKILL.md");
});
