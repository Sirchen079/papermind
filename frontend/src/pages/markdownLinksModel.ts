import type {Link, Root, RootContent} from 'mdast';
import remarkGfm from 'remark-gfm';
import remarkParse from 'remark-parse';
import {unified} from 'unified';

const literalParser = unified().use(remarkParse).use(remarkGfm);
const proseBoundary = /["“”‘’（）【】，。；：！？、]/;

/** GFM treats adjacent Chinese prose as part of a bare URL. Repair only those
 * auto links in the rendered tree; explicit Markdown links and stored text
 * retain their original destinations and content.
 */
export function remarkReadableAutolinks() {
  return (tree:Root, file:{value?:unknown} = {}) => {
    function split(link:Link, source:string):RootContent[] {
      if (link.children.length !== 1 || link.children[0].type !== 'text') return [link];
      const label = link.children[0].value;
      const prefix = link.url === label ? '' : link.url === 'http://' + label ? 'http://' : null;
      if (prefix === null || !/^(?:https?:\/\/|www\.)/i.test(label)) return [link];
      const offset = link.position?.start.offset;
      // Authored [label](destination) and <destination> may intentionally
      // contain international punctuation. Do not infer their URL boundaries.
      if (offset !== undefined && ['[','<'].includes(source[offset])) return [link];
      const boundary = label.search(proseBoundary);
      if (boundary < 1) return [link];
      const target = label.slice(0,boundary);
      const first:Link = {...link, url:prefix+target, position:undefined,
        children:[{type:'text',value:target}]};
      // Reuse the established parser for additional URLs swallowed by the
      // first autolink, including their explicit-link/code boundaries.
      const remaining = label.slice(boundary);
      const rest = literalParser.parse(remaining);
      const parsed = literalParser.runSync(rest) as Root;
      walk(parsed,remaining);
      const paragraph = parsed.children[0];
      return [first, ...(parsed.children.length === 1 && paragraph.type === 'paragraph'
        ? paragraph.children : [{type:'text' as const,value:remaining}])];
    }
    function walk(node:Root | RootContent, source:string) {
      if (!('children' in node) || ['link','linkReference'].includes(node.type)) return;
      node.children = node.children.flatMap(child => {
        if(child.type === 'link')return split(child,source);
        walk(child,source); return [child];
      }) as typeof node.children;
    }
    walk(tree,typeof file.value === 'string' ? file.value : '');
  };
}
