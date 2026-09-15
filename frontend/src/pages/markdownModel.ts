import type { Options } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import remarkBreaks from 'remark-breaks';
import rehypeKatex from 'rehype-katex';
import rehypeHighlight from 'rehype-highlight';

export const markdownRemarkPlugins: Options['remarkPlugins'] = [remarkGfm, remarkMath, remarkBreaks];
export const markdownRehypePlugins: Options['rehypePlugins'] = [
  [rehypeKatex, { trust: false, strict: 'ignore', maxExpand: 200, maxSize: 20, errorColor: 'currentColor' }],
  [rehypeHighlight, { detect: false }],
];

function escaped(text: string, index: number): boolean {
  let slashes = 0;
  for (let i = index - 1; i >= 0 && text[i] === '\\'; i--) slashes++;
  return slashes % 2 === 1;
}

/** Accept common model-produced TeX delimiters without rewriting code examples.
 * The message stored/copied by Chat stays untouched. An unfinished delimiter
 * stays as text while streaming and renders when its closing delimiter arrives.
 */
export function normalizeMathDelimiters(source: string): string {
  let result = '';
  let i = 0;
  while (i < source.length) {
    if (i === 0 || source[i - 1] === '\n') {
      const fence = /^( {0,3}(?:> ?)*)(`{3,}|~{3,})[^\n]*(?:\n|$)/.exec(source.slice(i));
      if (fence) {
        const close = new RegExp('^ {0,3}(?:> ?)*' + fence[2][0] + '{' + fence[2].length + ',}[ \\t]*$', 'm');
        const tail = source.slice(i + fence[0].length);
        const end = close.exec(tail);
        const length = end ? fence[0].length + end.index + end[0].length : source.length - i;
        result += source.slice(i, i + length); i += length; continue;
      }
      const indented = /^(?: {4}|\t)[^\n]*(?:\n|$)/.exec(source.slice(i));
      if (indented) { result += indented[0]; i += indented[0].length; continue; }
    }
    if (source[i] === '`' && !escaped(source, i)) {
      const run = /^`+/.exec(source.slice(i))![0];
      let end = source.indexOf(run, i + run.length);
      while (end >= 0 && (source[end - 1] === '`' || source[end + run.length] === '`')) end = source.indexOf(run, end + run.length);
      if (end >= 0) { result += source.slice(i, end + run.length); i = end + run.length; continue; }
      // An open code span may be a streaming prefix: don't rewrite its contents.
      result += source.slice(i); break;
    }
    if (source[i] === '\\' && !escaped(source, i) && (source[i + 1] === '(' || source[i + 1] === '[')) {
      const block = source[i + 1] === '[';
      const close = block ? '\\]' : '\\)';
      let end = source.indexOf(close, i + 2);
      while (end >= 0 && escaped(source, end)) end = source.indexOf(close, end + 2);
      if (end >= 0) {
        const body = source.slice(i + 2, end).trim();
        result += block ? '\n\n$$\n' + body + '\n$$\n\n' : '$' + body + '$';
        i = end + 2; continue;
      }
    }
    if (source[i] === '$' && !escaped(source, i)) {
      const delimiter = source[i + 1] === '$' ? '$$' : '$';
      let end = source.indexOf(delimiter, i + delimiter.length);
      while (end >= 0 && escaped(source, end)) end = source.indexOf(delimiter, end + delimiter.length);
      if (end >= 0) {
        const body = source.slice(i + delimiter.length, end);
        result += delimiter === '$$' ? '\n\n$$\n' + body.trim() + '\n$$\n\n' : source.slice(i, end + 1);
        i = end + delimiter.length; continue;
      }
    }
    result += source[i++];
  }
  return result;
}
