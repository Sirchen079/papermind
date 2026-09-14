import assert from "node:assert/strict";
import { test } from "node:test";

import { buildThesisLinkPayload } from "../.tmp_graph_test_dist/thesisLinkModel.js";

test("paper detail thesis link payload targets a project only", () => {
  assert.deepEqual(
    buildThesisLinkPayload({
      target_type: "project",
      project_id: "12",
      chapter_id: "34",
      role: "background",
      note: "  放在相关工作开头  ",
    }),
    { project_id: 12, role: "background", note: "放在相关工作开头" },
  );
});

test("paper detail thesis link payload targets a chapter only", () => {
  assert.deepEqual(
    buildThesisLinkPayload({
      target_type: "chapter",
      project_id: "12",
      chapter_id: "34",
      role: "evidence",
      note: "   ",
    }),
    { chapter_id: 34, role: "evidence" },
  );
});

test("paper detail thesis link payload rejects incomplete target selection", () => {
  assert.equal(
    buildThesisLinkPayload({
      target_type: "chapter",
      project_id: "12",
      chapter_id: "",
      role: "related",
      note: "",
    }),
    null,
  );
});
