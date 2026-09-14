import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readDraft, readResearchDraft, sameResearchEdit, writeDraft, clearMatchingDraft, syncResearchDraft } from '../.tmp_graph_test_dist/draftStorageModel.js';

function store() {
  const entries = new Map();
  return { getItem: key => entries.get(key) ?? null, setItem: (key, value) => entries.set(key, value), removeItem: key => entries.delete(key) };
}

test('draft survives remount, is isolated by paper and kind, and clears only the saved revision', () => {
  const storage = store();
  const empty = { content: '' };
  writeDraft(storage, 'paper-1-note', { content: 'first draft' });
  assert.deepEqual(readDraft(storage, 'paper-1-note', empty), { content: 'first draft' });
  assert.deepEqual(readDraft(storage, 'paper-2-note', empty), empty);
  assert.deepEqual(readDraft(storage, 'paper-1-excerpt', empty), empty);
  writeDraft(storage, 'paper-1-note', { content: 'edited during save' });
  assert.equal(clearMatchingDraft(storage, 'paper-1-note', { content: 'first draft' }, empty), false);
  assert.deepEqual(readDraft(storage, 'paper-1-note', empty), { content: 'edited during save' });
  assert.equal(clearMatchingDraft(storage, 'paper-1-note', { content: 'edited during save' }, empty), true);
  assert.deepEqual(readDraft(storage, 'paper-1-note', empty), empty);
});

test('storage failure preserves route drafts and cannot revive old text after a discard', () => {
  const storage = { getItem() { throw Error('disabled'); }, setItem() { throw Error('full'); }, removeItem() { throw Error('disabled'); } };
  const empty = { content: '' };
  assert.equal(writeDraft(storage, 'offline-note', { content: 'keep me' }), false);
  assert.deepEqual(readDraft(storage, 'offline-note', empty), { content: 'keep me' });
  clearMatchingDraft(storage, 'offline-note', { content: 'keep me' }, empty);
  assert.deepEqual(readDraft(storage, 'offline-note', empty), empty);
});

test('invalid storage and external removal do not restore obsolete draft memory', () => {
  const storage = store();
  const empty = { content: '' };
  storage.setItem('damaged', '{');
  assert.deepEqual(readDraft(storage, 'damaged', empty), empty);
  storage.setItem('damaged', '{"content":9}');
  assert.deepEqual(readDraft(storage, 'damaged', empty), empty);
  writeDraft(storage, 'external-clear', { content: 'old' });
  storage.removeItem('external-clear');
  assert.deepEqual(readDraft(storage, 'external-clear', empty), empty);
});

test('research undo to saved content removes that version but protects older versions', () => {
  const storage = store();
  syncResearchDraft(storage, 'task', { baseVersion: 2, content: 'withdrawn', refs: ['E1'] }, true);
  syncResearchDraft(storage, 'task', { baseVersion: 2, content: 'saved', refs: [] }, false);
  assert.equal(storage.getItem('task'), null);
  syncResearchDraft(storage, 'task', { baseVersion: 2, content: 'old draft', refs: ['E1'] }, true);
  syncResearchDraft(storage, 'task', { baseVersion: 3, content: 'new server version', refs: [] }, false);
  assert.equal(JSON.parse(storage.getItem('task')).content, 'old draft');
});

test('research drafts survive a full browser store', () => {
  const full = { getItem: () => null, setItem() { throw Error('quota'); }, removeItem() {} };
  const draft = {baseVersion: 1, content: 'Keep this research edit', refs: ['E1']};
  syncResearchDraft(full, 'offline-research', draft, true);
  assert.deepEqual(readDraft(full, 'offline-research', {baseVersion: -1, content: '', refs: []}), draft);
});

test('malformed compound draft fields do not pass shape validation', () => {
  const storage = store();
  for (const value of [{initialized: true, seen: null, unread: []}, {initialized: true, seen: {}, unread: {bad: true}}]) {
    storage.setItem('broken-activity', JSON.stringify(value));
    assert.deepEqual(readDraft(storage, 'broken-activity', {initialized:false, seen:{}, unread:[]}), {initialized:false, seen:{}, unread:[]});
  }
});

test('research restoration validates versions and evidence identifiers', () => {
  const storage = store();
  for (const value of [{baseVersion:1,content:'draft',refs:[null]}, {baseVersion:1.5,content:'draft',refs:[]}, {baseVersion:1,content:'draft',refs:{}}]) {
    storage.setItem('invalid-research', JSON.stringify(value));
    assert.equal(readResearchDraft(storage, 'invalid-research'), null);
  }
});

test('save completion keeps subsequent text and citation edits as a rebased draft', () => {
  const storage = store();
  const submitted = {baseVersion:1,content:'submitted',refs:['E1']};
  for (const edit of [{...submitted,content:'newer'}, {...submitted,refs:['E2']}]) {
    assert.equal(sameResearchEdit(submitted, edit), false);
    syncResearchDraft(storage, 'inflight-research', {...edit,baseVersion:2}, true);
    assert.deepEqual(readResearchDraft(storage, 'inflight-research'), {...edit,baseVersion:2});
  }
});
