import assert from "node:assert/strict";
import { test } from "node:test";

import {
  shouldCloseOnEscape,
  shouldSubmitOnEnter,
  chatEnterAction,
} from "../.tmp_graph_test_dist/keyGuardModel.js";

test('conversation Enter sends, Ctrl/Cmd/Shift+Enter inserts a newline, IME never sends', () => {
  const event = {key: 'Enter', ctrlKey: false, metaKey: false, shiftKey: false, isComposing: false};
  assert.equal(chatEnterAction(event), 'send');
  for (const key of ['ctrlKey', 'metaKey', 'shiftKey']) assert.equal(chatEnterAction({...event, [key]: true}), 'newline');
  assert.equal(chatEnterAction({...event, isComposing: true}), null);
  assert.equal(chatEnterAction({...event, keyCode: 229}), null);
  assert.equal(chatEnterAction({...event, key: 'a'}), null);
});

test("chat input submits on Enter without Shift and outside IME composition", () => {
  assert.equal(shouldSubmitOnEnter("Enter", false, false), true);
});

test("chat input does not submit on Enter with Shift held", () => {
  assert.equal(shouldSubmitOnEnter("Enter", true, false), false);
});

test("chat input does not submit on Enter during IME composition", () => {
  assert.equal(shouldSubmitOnEnter("Enter", false, true), false);
});

test("input never submits on keys other than Enter", () => {
  assert.equal(shouldSubmitOnEnter("a", false, false), false);
  assert.equal(shouldSubmitOnEnter("Escape", false, false), false);
  assert.equal(shouldSubmitOnEnter("ArrowDown", false, false), false);
  assert.equal(shouldSubmitOnEnter("", true, true), false);
});

test("rename dialog confirms only on plain Enter via shiftKey=false", () => {
  // 单行重命名输入框复用同一守卫：shiftKey 固定传 false
  assert.equal(shouldSubmitOnEnter("Enter", false, false), true);
});

test("rename dialog ignores Enter during IME composition via shiftKey=false", () => {
  // 输入法组词阶段回车仅上屏候选词，不触发确认
  assert.equal(shouldSubmitOnEnter("Enter", false, true), false);
});

test("guard allows Enter combined with other modifiers as long as Shift is up", () => {
  // Ctrl/Cmd+Enter 仍视为提交意图（shiftKey=false 且非组词）
  assert.equal(shouldSubmitOnEnter("Enter", false, false), true);
});

test("Escape closes reader/detail when no alertdialog is present", () => {
  // 页面没有 [role="alertdialog"] 时保持原行为：Escape 允许关闭
  assert.equal(shouldCloseOnEscape("Escape", false), true);
});

test("Escape must not close underlying reader/detail while an alertdialog is open", () => {
  // 确认弹窗（alertdialog）在前时，全局 Escape 不得关闭底层阅读器/详情
  assert.equal(shouldCloseOnEscape("Escape", true), false);
});

test("non-Escape keys never close reader/detail", () => {
  assert.equal(shouldCloseOnEscape("a", false), false);
});
