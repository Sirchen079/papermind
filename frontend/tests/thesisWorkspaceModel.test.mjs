import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildThesisMarkdownExportTarget,
  chapterDeleteBlockReason,
  collectLinkedThesisTargetIds,
  projectDeleteBlockReason,
} from "../.tmp_graph_test_dist/thesisWorkspaceModel.js";

test("collects linked project and chapter targets from workspace papers", () => {
  const ids = collectLinkedThesisTargetIds([
    {
      links: [
        { project_id: 1, chapter_id: null },
        { project_id: null, chapter_id: 7 },
      ],
    },
    { links: [{ project_id: 2, chapter_id: null }] },
  ]);

  assert.deepEqual([...ids.projectIds].sort(), [1, 2]);
  assert.deepEqual([...ids.chapterIds], [7]);
});

test("project deletion is blocked by children, chapters, or linked papers", () => {
  assert.equal(
    projectDeleteBlockReason({ id: 1, children: [{ id: 2 }], chapters: [] }, new Set()),
    "项目下还有子项目",
  );
  assert.equal(
    projectDeleteBlockReason({ id: 1, children: [], chapters: [{ id: 3 }] }, new Set()),
    "项目下还有章节",
  );
  assert.equal(
    projectDeleteBlockReason({ id: 1, children: [], chapters: [] }, new Set([1])),
    "项目下还有论文链接",
  );
  assert.equal(projectDeleteBlockReason({ id: 1, children: [], chapters: [] }, new Set()), null);
});

test("chapter deletion is blocked by child chapters or linked papers", () => {
  assert.equal(
    chapterDeleteBlockReason({ id: 7, children: [{ id: 8 }] }, new Set()),
    "章节下还有子章节",
  );
  assert.equal(
    chapterDeleteBlockReason({ id: 7, children: [] }, new Set([7])),
    "章节下还有论文链接",
  );
  assert.equal(chapterDeleteBlockReason({ id: 7, children: [] }, new Set()), null);
});

test("thesis markdown export target requires the selected scope", () => {
  assert.deepEqual(buildThesisMarkdownExportTarget("project", 3, 9), { project_id: 3 });
  assert.deepEqual(buildThesisMarkdownExportTarget("chapter", 3, 9), { chapter_id: 9 });
  assert.equal(buildThesisMarkdownExportTarget("project", null, 9), null);
  assert.equal(buildThesisMarkdownExportTarget("chapter", 3, null), null);
});
