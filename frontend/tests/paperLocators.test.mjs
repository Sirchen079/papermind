import assert from 'node:assert/strict';
import {test} from 'node:test';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ReactMarkdown from 'react-markdown';
import {markdownRemarkPlugins} from '../.tmp_graph_test_dist/markdownModel.js';
import {remarkPaperLocators,pdfLocatorTarget} from '../.tmp_graph_test_dist/paperLocatorModel.js';

function render(text,paperId=1004) {
  return renderToStaticMarkup(React.createElement(ReactMarkdown,{remarkPlugins:[...markdownRemarkPlugins,[remarkPaperLocators,{paperId}]]},text));
}
test('Nature card points to explicit PDF file pages and keeps structural descriptions',()=>{
  const html=render('[Paper: PDF p. 3, Figure 1; PDF p. 4, Section 3]');
  assert.match(html,/href="#pm-pdf-1004-3"/);
  assert.match(html,/href="#pm-pdf-1004-4"/);
  assert.match(html,/Figure 1; /);
  assert.match(html,/Section 3/);
});
test('ranges open their first page with an explicit range label, including analysis pointers',()=>{
  const html=render('[Analysis based on Paper: PDF pp. 4–5, Figures 2–3]');
  assert.match(html,/href="#pm-pdf-1004-4"/);
  assert.match(html,/引用范围 4–5 页/);
  assert.match(html,/Figures 2–3/);
});
test('code, authored links, printed pages and ambiguous paper identity are not reinterpreted',()=>{
  const text='`[Paper: PDF p. 3]`\n\n```text\n[Paper: PDF p. 4]\n```\n\n[Paper: PDF p. 5](https://example.org)\n\n[Paper: printed p. 2]';
  const html=render(text);
  assert.doesNotMatch(html,/#pm-pdf-/);
  assert.match(html,/href="https:\/\/example.org"/);
  assert.doesNotMatch(render('[Paper: PDF p. 3]',null),/#pm-pdf-/);
  assert.doesNotMatch(render('[Paper: Section 3; p. 2]'),/#pm-pdf-/);
});
test('table cells retain clickable locators without changing the original source',()=>{
  const source='| Evidence |\n|---|\n| [Paper: PDF p. 3, Eq. 4] |';
  const before=source;
  assert.match(render(source),/<td>\[Paper: <a href="#pm-pdf-1004-3"/);
  assert.equal(source,before);
});
test('incomplete streaming citations and invalid page ranges remain text',()=>{
  for(const text of ['[Paper: PDF p. 0]', '[Paper: PDF pp. 5–3]', '[Paper: PDF pp. 3–0]', '[Paper: PDF pp. 3–4.5]', '[Paper: PDF p. 3', '[Paper: PDF p. 1.5]'])
    assert.doesNotMatch(render(text),/#pm-pdf-/);
  assert.deepEqual(pdfLocatorTarget('#pm-pdf-1004-3'),{paperId:1004,page:3});
  assert.equal(pdfLocatorTarget('#pm-pdf-1004-0'),null);
  assert.equal(pdfLocatorTarget('#pm-pdf-1004-3?other=4'),null);
});
