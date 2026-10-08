import type {Root, RootContent, Text, Link} from 'mdast';

/** Nature's paper-relative locators only resolve where a paper identity is known.
 * Work on Markdown text nodes so code examples and existing links stay intact.
 */
export function remarkPaperLocators({paperId}:{paperId?:number} = {}) {
  return (tree:Root) => {
    if (!Number.isSafeInteger(paperId) || paperId! < 1) return;
    function split(node:Text):RootContent[] {
      const parts:RootContent[] = [];
      let cursor = 0;
      for (const pointer of node.value.matchAll(/\[(?:Paper:|Analysis based on Paper:)[^\]\n]+\]/g)) {
        for (const page of pointer[0].matchAll(/PDF\s+p{1,2}\.\s*(\d+)(?:\s*[–—-]\s*(\d+))?(?![\d.]|\s*[–—-])/g)) {
          const first = Number(page[1]), last = page[2] ? Number(page[2]) : first;
          if (!Number.isSafeInteger(first) || !Number.isSafeInteger(last) || first < 1 || last < first) continue;
          const start = pointer.index! + page.index!;
          parts.push({type:'text', value:node.value.slice(cursor,start)});
          const title = `查看 PDF 第 ${first} 页` + (last !== first ? `（引用范围 ${first}–${last} 页）` : '');
          const link:Link = {type:'link', url:`#pm-pdf-${paperId}-${first}`, title,
            children:[{type:'text',value:page[0]}]};
          parts.push(link); cursor = start + page[0].length;
        }
      }
      if (!cursor) return [node];
      parts.push({type:'text',value:node.value.slice(cursor)});
      return parts;
    }
    function walk(node:Root | RootContent) {
      if (!('children' in node) || ['link','linkReference'].includes(node.type)) return;
      node.children = node.children.flatMap(child => {
        if(child.type==='text')return split(child);
        walk(child); return [child];
      }) as typeof node.children;
    }
    walk(tree);
  };
}

export function pdfLocatorTarget(href?:string):{paperId:number;page:number}|null {
  const match = /^#pm-pdf-([1-9]\d*)-([1-9]\d*)$/.exec(href??'');
  if (!match) return null;
  const paperId = Number(match[1]), page = Number(match[2]);
  return Number.isSafeInteger(paperId)&&Number.isSafeInteger(page)?{paperId,page}:null;
}
