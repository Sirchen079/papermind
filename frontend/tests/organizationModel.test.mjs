import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildCollectionPayload,
  buildTagPayload,
  matchesOrganizationFilter,
} from "../.tmp_graph_test_dist/organizationModel.js";

test("tag payload trims Chinese name and optional color", () => {
  assert.deepEqual(buildTagPayload({ name: " 核心方法 ", color: " #2563eb " }), {
    name: "核心方法",
    color: "#2563eb",
  });
});

test("tag payload rejects empty name", () => {
  assert.equal(buildTagPayload({ name: "  ", color: "#2563eb" }), null);
});

test("collection payload normalizes description", () => {
  assert.deepEqual(buildCollectionPayload({ name: " 毕业论文必读 ", description: " 相关工作 " }), {
    name: "毕业论文必读",
    description: "相关工作",
  });
  assert.deepEqual(buildCollectionPayload({ name: "资料夹", description: " " }), {
    name: "资料夹",
    description: null,
  });
});

test("organization filter matches tags and collections independently", () => {
  const paper = {
    tags: [{ id: 1, name: "核心方法", color: null }],
    collections: [{ id: 2, name: "毕业论文必读" }],
  };
  assert.equal(matchesOrganizationFilter(paper, "all"), true);
  assert.equal(matchesOrganizationFilter(paper, "tag:1"), true);
  assert.equal(matchesOrganizationFilter(paper, "tag:99"), false);
  assert.equal(matchesOrganizationFilter(paper, "collection:2"), true);
  assert.equal(matchesOrganizationFilter(paper, "collection:99"), false);
});
