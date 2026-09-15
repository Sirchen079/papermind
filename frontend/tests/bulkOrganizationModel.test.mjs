import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildBulkOrganizationPayload,
  replaceBulkPaperSelection,
  toggleBulkPaperSelection,
} from "../.tmp_graph_test_dist/bulkOrganizationModel.js";

test("bulk paper selection toggles one paper without disturbing existing order", () => {
  assert.deepEqual(toggleBulkPaperSelection([3, 1], 5), [3, 1, 5]);
  assert.deepEqual(toggleBulkPaperSelection([3, 1, 5], 1), [3, 5]);
});

test("bulk paper selection keeps visible ids unique and valid", () => {
  assert.deepEqual(replaceBulkPaperSelection([4, 4, -1, 2, 0, 2]), [4, 2]);
});

test("bulk organization payload requires selected papers and a positive target", () => {
  assert.deepEqual(buildBulkOrganizationPayload([2, 2, 7], "5"), {
    paperIds: [2, 7],
    targetId: 5,
  });
  assert.equal(buildBulkOrganizationPayload([], "5"), null);
  assert.equal(buildBulkOrganizationPayload([2], ""), null);
  assert.equal(buildBulkOrganizationPayload([2], "0"), null);
});
