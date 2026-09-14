import assert from "node:assert/strict";
import { test } from "node:test";

import { parseApiErrorMessage } from "../.tmp_graph_test_dist/apiErrorModel.js";

test("400 JSON detail string is rendered as status plus Chinese message", () => {
  assert.equal(parseApiErrorMessage(400, '{"detail":"标题不能为空"}'), "400 标题不能为空");
});

test("422 FastAPI detail array joins each object's msg with semicolons", () => {
  const body = JSON.stringify({
    detail: [
      { loc: ["body", "title"], msg: "Field required", type: "missing" },
      { loc: ["body", "year"], msg: "Input should be valid", type: "value_error" },
    ],
  });
  assert.equal(parseApiErrorMessage(422, body), "422 Field required; Input should be valid");
});

test("502 non-JSON HTML body falls back to raw text, trimmed and capped at 200 chars", () => {
  assert.equal(parseApiErrorMessage(502, "<html>Bad gateway</html>"), "502 <html>Bad gateway</html>");
  // 额外要求：非 JSON 回退需先 trim 再截断到最多 200 字符
  const long = "x".repeat(250);
  assert.equal(parseApiErrorMessage(502, `  ${long}  `), `502 ${"x".repeat(200)}`);
});

test("400 JSON object without detail field falls back to raw body text", () => {
  assert.equal(parseApiErrorMessage(400, '{"error":"bad"}'), '400 {"error":"bad"}');
});

test("500 blank body falls back to default Chinese failure message", () => {
  assert.equal(parseApiErrorMessage(500, "   \n\t "), "500 请求失败");
});
