import assert from 'node:assert/strict';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ReactMarkdown from 'react-markdown';
import { markdownRehypePlugins, markdownRemarkPlugins, normalizeMathDelimiters } from '../.tmp_graph_test_dist/markdownModel.js';

function render(content) {
  return renderToStaticMarkup(React.createElement(ReactMarkdown, {
    remarkPlugins: markdownRemarkPlugins, rehypePlugins: markdownRehypePlugins, skipHtml: true,
  }, normalizeMathDelimiters(content)));
}

test('ordinary chat line breaks remain visible outside code and math', () => {
  assert.match(render('First line\nSecond line'),/First line<br\/>\nSecond line/);
});

test('Markdown headings, emphasis, lists, quotes, links, tasks and tables render semantically', () => {
  const html = render('# Heading\n\n**bold** and *italic* and ~~deleted~~\n\n> Quote\n\n1. Ordered\n\n- [x] done\n- [ ] next\n\n| A | B |\n|---|---|\n| one | two |\n\n[Source](https://example.org)');
  for (const tag of ['h1','strong','em','del','blockquote','ol','table','th','td']) assert.match(html,new RegExp(`<${tag}[ >]`));
  assert.match(html,/type="checkbox"/);
  assert.match(html,/href="https:\/\/example.org"/);
});

test('both inline TeX delimiter families produce accessible formula markup', () => {
  const html = render(String.raw`Energy $E=mc^2$ and \(\alpha + \beta\).`);
  assert.equal((html.match(/class="katex"/g)||[]).length,2);
  assert.match(html,/<math /);
  assert.doesNotMatch(html,/katex-display/);
});

test('display TeX supports fractions, aligned equations, matrices and one-line dollar blocks', () => {
  const html = render(String.raw`\[\begin{aligned}a &= \frac{b}{c} \\ M &= \begin{bmatrix}1&0\\0&1\end{bmatrix}\end{aligned}\]` + '\n\n$$x^2 + y^2 = 1$$');
  assert.equal((html.match(/class="katex-display"/g)||[]).length,2);
  assert.doesNotMatch(html,/katex-error/);
});

test('math delimiters inside inline, fenced, quoted and indented code stay literal', () => {
  const samples = [
    '`\\(x\\) and $y$`',
    '``one ` \\[x\\]``',
    '```python\nprint("\\(x\\) $5$")\n```',
    '~~~text\n\\[x\\]\n~~~',
    '> ```text\n> \\(x\\)\n> ```',
    '    \\(x\\) and $$y$$',
    '```python\n\\(unfinished fence\\)',
  ];
  for (const sample of samples) {
    assert.equal(normalizeMathDelimiters(sample),sample);
    assert.doesNotMatch(render(sample),/class="katex"/);
  }
});

test('code highlighting preserves source and tolerates unknown fence languages', () => {
  const html = render('```python\ndef square(x):\n    return x ** 2\n```');
  assert.match(html,/hljs-keyword/);
  assert.match(html,/square/);
  assert.doesNotThrow(()=>render('```unknown-language\n<literal> $x$\n```'));
});

test('unfinished streaming formulas and malformed TeX cannot break the rest of a message', () => {
  const source = String.raw`Start \[\frac{a+b}{c}\] end`;
  for (const length of [1,7,8,11,16,source.length-2,source.length]) assert.doesNotThrow(()=>render(source.slice(0,length)));
  const html = render(String.raw`$\unknowncommand{x}$`+'\n\nStill readable');
  assert.match(html,/unknowncommand/);
  assert.match(html,/Still readable/);
  assert.match(render(String.raw`$\frac{a}{$`),/katex-error/);
});

test('escaped currency and literal backslashes are not rewritten as equations', () => {
  const source = String.raw`Cost \$5; path \\(name\\); escaped \[ without closing.`;
  assert.equal(normalizeMathDelimiters(source),source);
  assert.doesNotMatch(render(source),/class="katex"/);
});

test('raw HTML, unsafe links and trusted TeX commands do not create executable content', () => {
  const html = render('<script>alert(1)</script>\n\n[bad](javascript:alert%281%29)\n\n'+String.raw`$\href{javascript:alert(1)}{link}$`);
  assert.doesNotMatch(html,/<script|href="javascript:/);
  assert.doesNotMatch(html,/<iframe/);
});

test('Chinese prose and quotes cannot become part of a bare resource URL', () => {
  const source = '论文称"资源在 https://example.org/"。实际读取该页（https://example.org/），还有代码（https://github.com/example/repo）、数据（https://example.org/data）及演示。';
  const html = render(source);
  assert.deepEqual([...html.matchAll(/href="([^"]*)"/g)].map(match=>match[1]), [
    'https://example.org/', 'https://example.org/', 'https://github.com/example/repo', 'https://example.org/data',
  ]);
  assert.match(html,/实际读取该页/);
  assert.match(html,/还有代码/);
  assert.match(html,/及演示。/);
});

test('bare URLs in table cells keep Chinese punctuation outside the target', () => {
  const html = render('| 资源 | 说明 |\n|---|---|\n| https://example.org/model，https://example.org/data。 | 另见 www.example.org/demo）；完成 |');
  assert.deepEqual([...html.matchAll(/href="([^"]*)"/g)].map(match=>match[1]), [
    'https://example.org/model', 'https://example.org/data', 'http://www.example.org/demo',
  ]);
  assert.match(html,/<table>/);
  assert.match(html,/完成/);
});

test('explicit and international URLs, encoded punctuation and query strings retain their destinations', () => {
  const html = render('[中文目录](https://example.org/目录（版本）)\n\nhttps://example.org/资料?q=中文&tag=a%EF%BC%89b。\n\n<https://example.org/目录（版本）>\n\n[quoted](https://example.org/%22file%22)');
  assert.deepEqual([...html.matchAll(/href="([^"]*)"/g)].map(match=>match[1]), [
    'https://example.org/%E7%9B%AE%E5%BD%95%EF%BC%88%E7%89%88%E6%9C%AC%EF%BC%89',
    'https://example.org/%E8%B5%84%E6%96%99?q=%E4%B8%AD%E6%96%87&amp;tag=a%EF%BC%89b',
    'https://example.org/%E7%9B%AE%E5%BD%95%EF%BC%88%E7%89%88%E6%9C%AC%EF%BC%89', 'https://example.org/%22file%22',
  ]);
});

test('literal URL repair leaves code, mail, fragments and unsafe explicit links unchanged', () => {
  const html = render('`https://example.org/path）。`\n\n```text\nhttps://example.org/path）。\n```\n\ncontact@example.org\n\n[page](#pm-pdf-1-7)\n\n[bad](javascript:alert%281%29)');
  assert.equal((html.match(/href="https:/g)||[]).length,0);
  assert.match(html,/href="mailto:contact@example.org"/);
  assert.match(html,/href="#pm-pdf-1-7"/);
  assert.doesNotMatch(html,/href="javascript:/);
  assert.match(html,/https:\/\/example.org\/path）。/);
});
