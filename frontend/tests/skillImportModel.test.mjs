import assert from "node:assert/strict";
import { test } from "node:test";

import {
  canUpdate,
  githubSourceUrl,
  githubUrlError,
  shortRevision,
  sourceKind,
} from "../.tmp_graph_test_dist/skillImportModel.js";

test("githubUrlError 接受仓库根地址与子目录地址", () => {
  assert.equal(githubUrlError("https://github.com/anthropics/skills"), null);
  assert.equal(githubUrlError("  https://github.com/anthropics/skills  "), null);
  assert.equal(githubUrlError("https://github.com/anthropics/skills/"), null);
  assert.equal(
    githubUrlError("https://github.com/anthropics/skills/tree/main/document-skills/pdf"),
    null,
  );
  assert.equal(githubUrlError("https://github.com/a/b/tree/main"), null);
});

test("githubUrlError 拒绝空值、非 GitHub 与不完整地址", () => {
  assert.equal(githubUrlError(""), "请填写 GitHub 地址");
  assert.equal(githubUrlError("   "), "请填写 GitHub 地址");
  assert.equal(
    githubUrlError("https://gitlab.com/owner/repo"),
    "请使用 https://github.com/<owner>/<repo> 形式的地址",
  );
  assert.equal(
    githubUrlError("github.com/owner/repo"),
    "请使用 https://github.com/<owner>/<repo> 形式的地址",
  );
  assert.equal(githubUrlError("https://github.com/owner"), "地址里缺少 owner 或 repo 名");
  assert.equal(githubUrlError("https://github.com/"), "地址里缺少 owner 或 repo 名");
  assert.equal(
    githubUrlError("https://github.com/owner/repo/blob/main/README.md"),
    "子目录请写成 /tree/<分支>/<目录> 形式",
  );
  assert.equal(
    githubUrlError("https://github.com/owner/repo/tree"),
    "子目录请写成 /tree/<分支>/<目录> 形式",
  );
});

test("sourceKind 区分 GitHub、文件夹与 zip 来源", () => {
  assert.equal(sourceKind("https://github.com/owner/repo"), "github");
  assert.equal(sourceKind("https://github.com/owner/repo/tree/main/skills"), "github");
  assert.equal(sourceKind("https://www.github.com/owner/repo"), "github");
  assert.equal(sourceKind("C:\\Users\\me\\skills"), "folder");
  assert.equal(sourceKind("F:/论文管理/skills"), "folder");
  assert.equal(sourceKind("/home/me/skills"), "folder");
  assert.equal(sourceKind("zip:skills.zip"), "zip");
  assert.equal(sourceKind("zip:从剪贴板导入.zip"), "zip");
});

test("githubSourceUrl 只为合法 GitHub 地址返回可点开链接", () => {
  assert.equal(
    githubSourceUrl("https://github.com/owner/repo"),
    "https://github.com/owner/repo",
  );
  assert.equal(
    githubSourceUrl("https://www.github.com/owner/repo/tree/main/skills"),
    "https://www.github.com/owner/repo/tree/main/skills",
  );
  assert.equal(githubSourceUrl("C:\\Users\\me\\skills"), null);
  assert.equal(githubSourceUrl("zip:skills.zip"), null);
  assert.equal(githubSourceUrl("https://github.com/owner"), null);
  assert.equal(githubSourceUrl("https://github.com/"), null);
});

test("canUpdate 仅 GitHub 与文件夹来源可更新", () => {
  assert.equal(canUpdate("https://github.com/owner/repo"), true);
  assert.equal(canUpdate("C:\\Users\\me\\skills"), true);
  assert.equal(canUpdate("zip:skills.zip"), false);
  assert.equal(canUpdate(""), false);
});

test("shortRevision 截断 commit sha，短版本原样保留", () => {
  assert.equal(shortRevision("a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"), "a1b2c3d");
  assert.equal(shortRevision("a1b2c3d"), "a1b2c3d");
  assert.equal(shortRevision("main"), "main");
  assert.equal(shortRevision(""), "");
  assert.equal(shortRevision("  a1b2c3d4  "), "a1b2c3d");
});
