import { test } from 'node:test';
import assert from 'node:assert/strict';
import { retryPaperIds, institutionalLabel, downloadSelectionValid } from '../.tmp_graph_test_dist/institutionalModel.js';

test('continuing a job preserves completed downloads and skips deleted papers', () => {
  assert.deepEqual(retryPaperIds([{paper_id:1,status:'attached'}, {paper_id:2,status:'pending'},
    {paper_id:3,status:'has_pdf'}, {paper_id:4,status:'not_found'}, {paper_id:5,status:'waiting_user'}]), [2,5]);
});
test('manual fallback accepts one paper and automatic selection remains bounded', () => {
  assert.ok(downloadSelectionValid([1], 'manual'));
  assert.equal(downloadSelectionValid([1,2], 'manual'), false);
  assert.equal(downloadSelectionValid([], 'auto'), false);
  assert.equal(downloadSelectionValid(Array.from({length:11},(_,i)=>i+1), 'auto'), false);
});
test('identity, entitlement and authentication failures remain distinct', () => {
  assert.equal(institutionalLabel('environment_failed'), '下载环境准备失败');
  assert.equal(institutionalLabel('worker_failed'), '下载引擎未返回结果');
  assert.equal(institutionalLabel('attached'), 'PDF 已入库');
  assert.notEqual(institutionalLabel('unverified'), institutionalLabel('no_permission'));
  assert.notEqual(institutionalLabel('waiting_user'), institutionalLabel('needs_attention'));
  assert.match(institutionalLabel('waiting_verification'), /人机验证/);
  assert.notEqual(institutionalLabel('waiting_verification'), institutionalLabel('waiting_login'));
});
