import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_PAGE,
  buildHash,
  libraryDeepLinkFromParams,
  libraryParamsFromState,
  parseHash,
  readinessCheckLocation,
  researchActionLocation,
  sameLocation,
} from "../.tmp_graph_test_dist/navigationModel.js";

test("navigation model parses plain top-level hashes", () => {
  assert.deepEqual(parseHash(""), { page: DEFAULT_PAGE, params: {} });
  assert.deepEqual(parseHash("#"), { page: DEFAULT_PAGE, params: {} });
  assert.deepEqual(parseHash("#home"), { page: "home", params: {} });
  assert.deepEqual(parseHash("#library"), { page: "library", params: {} });
  assert.deepEqual(parseHash("#settings"), { page: "settings", params: {} });
  assert.deepEqual(parseHash("#graph"), { page: "graph", params: {} });
});

test("navigation model parses library deep-link params", () => {
  assert.deepEqual(parseHash("#library?view=matrix"), {
    page: "library",
    params: { view: "matrix" },
  });
  assert.deepEqual(parseHash("#library?import=pdf"), {
    page: "library",
    params: { import: "pdf" },
  });
  assert.deepEqual(parseHash("#library?status=queued&view=thesis"), {
    page: "library",
    params: { status: "queued", view: "thesis" },
  });
});

test("navigation model falls back safely on invalid input", () => {
  assert.equal(parseHash("#nope").page, DEFAULT_PAGE);
  assert.equal(parseHash("#nope?view=matrix").page, DEFAULT_PAGE);
  assert.equal(parseHash("#library?view=bogus").page, "library");
  assert.deepEqual(parseHash("#library?view=bogus").params, { view: "bogus" });
  assert.equal(parseHash("library?view=matrix").page, "library");
  assert.deepEqual(parseHash("#settings?leftover=1").params, { leftover: "1" });
});

test("navigation model builds canonical hashes", () => {
  assert.equal(buildHash({ page: DEFAULT_PAGE, params: {} }), "");
  assert.equal(buildHash({ page: "library", params: {} }), "#library");
  assert.equal(buildHash({ page: "library", params: { view: "matrix" } }), "#library?view=matrix");
  assert.equal(buildHash({ page: "settings", params: {} }), "#settings");
  assert.equal(
    buildHash({ page: "library", params: { view: "thesis", status: "queued" } }),
    "#library?status=queued&view=thesis",
  );
});

test("navigation model compares locations ignoring param order", () => {
  assert.ok(
    sameLocation(
      { page: "library", params: { view: "thesis", status: "queued" } },
      { page: "library", params: { status: "queued", view: "thesis" } },
    ),
  );
  assert.ok(
    !sameLocation(
      { page: "library", params: { view: "thesis" } },
      { page: "library", params: { view: "matrix" } },
    ),
  );
  assert.ok(
    !sameLocation(
      { page: "library", params: {} },
      { page: "library", params: { view: "library" } },
    ),
  );
  assert.ok(!sameLocation({ page: "library", params: {} }, { page: "chat", params: {} }));
});

test("library deep link applies params to inner state with safe fallbacks", () => {
  assert.deepEqual(libraryDeepLinkFromParams({}), {
    view: "library",
    importOpen: false,
    importTab: "manual",
    readingStatus: "all",
  });
  assert.deepEqual(libraryDeepLinkFromParams({ view: "matrix" }).view, "matrix");
  assert.deepEqual(libraryDeepLinkFromParams({ view: "thesis" }).view, "thesis");
  assert.deepEqual(libraryDeepLinkFromParams({ view: "bogus" }).view, "library");
  assert.deepEqual(libraryDeepLinkFromParams({ import: "pdf" }).importOpen, true);
  assert.deepEqual(libraryDeepLinkFromParams({ import: "pdf" }).importTab, "pdf");
  assert.deepEqual(libraryDeepLinkFromParams({ import: "bogus" }).importOpen, false);
  assert.deepEqual(libraryDeepLinkFromParams({ status: "queued" }).readingStatus, "queued");
  assert.deepEqual(libraryDeepLinkFromParams({ status: "bogus" }).readingStatus, "all");
});

test("library params from state omit defaults so canonical hash stays clean", () => {
  assert.deepEqual(libraryParamsFromState({}), {});
  assert.deepEqual(
    libraryParamsFromState({ view: "library", importOpen: false, importTab: "manual", readingStatus: "all" }),
    {},
  );
  assert.deepEqual(libraryParamsFromState({ view: "matrix" }), { view: "matrix" });
  assert.deepEqual(libraryParamsFromState({ importOpen: true, importTab: "pdf" }), { import: "pdf" });
  assert.deepEqual(libraryParamsFromState({ readingStatus: "queued" }), { status: "queued" });
});

test("library deep link round-trips through buildHash and parseHash", () => {
  const cases = [
    { view: "matrix" },
    { view: "thesis" },
    { importOpen: true, importTab: "arxiv" },
    { readingStatus: "read" },
    { view: "thesis", readingStatus: "queued" },
  ];
  for (const state of cases) {
    const params = libraryParamsFromState(state);
    const hash = buildHash({ page: "library", params });
    const parsed = parseHash(hash);
    const restored = libraryDeepLinkFromParams(parsed.params);
    assert.deepEqual(restored, libraryDeepLinkFromParams(params));
  }
});

test("readiness checks map to concrete deep-link targets", () => {
  assert.deepEqual(readinessCheckLocation("llm"), { page: "settings", params: {} });
  assert.deepEqual(readinessCheckLocation("embedding"), { page: "settings", params: {} });
  assert.deepEqual(readinessCheckLocation("library"), {
    page: "library",
    params: { import: "pdf" },
  });
  assert.deepEqual(readinessCheckLocation("analysis"), { page: "library", params: {} });
  assert.deepEqual(readinessCheckLocation("rag"), { page: "settings", params: {} });
  assert.deepEqual(readinessCheckLocation("graph"), { page: "graph", params: {} });
  assert.deepEqual(readinessCheckLocation("reading"), {
    page: "library",
    params: { status: "reading" },
  });
  assert.deepEqual(readinessCheckLocation("writing"), {
    page: "library",
    params: { view: "thesis" },
  });
});

test("readiness checks fall back to the backend route for unknown ids", () => {
  assert.deepEqual(readinessCheckLocation("future_check", "graph"), { page: "graph", params: {} });
  assert.deepEqual(readinessCheckLocation("future_check", "library"), { page: "library", params: {} });
  assert.deepEqual(readinessCheckLocation("future_check"), { page: "home", params: {} });
});

test("research actions map to concrete deep-link targets", () => {
  assert.deepEqual(researchActionLocation("import_papers"), {
    page: "library",
    params: { import: "pdf" },
  });
  assert.deepEqual(researchActionLocation("fix_library_quality"), { page: "home", params: {} });
  assert.deepEqual(researchActionLocation("process_reading_queue"), {
    page: "library",
    params: { status: "queued" },
  });
  assert.deepEqual(researchActionLocation("build_review_matrix"), {
    page: "library",
    params: { view: "matrix" },
  });
  assert.deepEqual(researchActionLocation("create_thesis_structure"), {
    page: "library",
    params: { view: "thesis" },
  });
  assert.deepEqual(researchActionLocation("link_read_papers_to_thesis"), {
    page: "library",
    params: { view: "thesis" },
  });
  assert.deepEqual(researchActionLocation("continue_research_loop"), { page: "library", params: {} });
});

test("research actions fall back to the backend route for unknown ids", () => {
  assert.deepEqual(researchActionLocation("future_action", "settings"), { page: "settings", params: {} });
  assert.deepEqual(researchActionLocation("future_action"), { page: "home", params: {} });
});
