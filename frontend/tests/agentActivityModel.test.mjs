import test from 'node:test';
import assert from 'node:assert/strict';
import { agentActivityLabel } from '../.tmp_graph_test_dist/agentActivityModel.js';

test('activity follows actual tools and stages, with brainstorming only during thinking', () => {
  assert.equal(agentActivityLabel('thinking', undefined, '讨论一个idea'), '正在构思研究思路');
  assert.equal(agentActivityLabel('tool', 'get_paper_full_text', '讨论一个idea'), '正在阅读论文全文');
  assert.equal(agentActivityLabel('tool', 'save_research_idea'), '正在保存研究灵感');
  assert.equal(agentActivityLabel('responding', undefined, '讨论一个idea'), '正在整理回答');
  assert.equal(agentActivityLabel('tool', 'unknown'), '正在使用研究工具');
});
