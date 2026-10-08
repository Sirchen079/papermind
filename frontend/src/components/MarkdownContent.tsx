import { memo, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import type {Options} from 'react-markdown';
import { markdownRehypePlugins, markdownRemarkPlugins, normalizeMathDelimiters } from '../pages/markdownModel';
import 'katex/dist/katex.min.css';
import {remarkPaperLocators,pdfLocatorTarget} from '../pages/paperLocatorModel';
import './markdown.css';

/** One renderer for both sides of the conversation, including streamed replies. */
export const MarkdownContent = memo(function MarkdownContent({ content, images = true, onPaperCitation, paperId, onPdfPage }: { content: string; images?: boolean; onPaperCitation?:(id:number)=>void; paperId?:number; onPdfPage?:(id:number,page:number)=>void }) {
  const markdown = useMemo(() => normalizeMathDelimiters(onPaperCitation ? content.replace(/\[P(\d+)\](?!\()/g,'[P$1](#pm-paper-$1)') : content), [content,onPaperCitation]);
  const plugins = useMemo<Options['remarkPlugins']>(() => onPdfPage && paperId ? [...markdownRemarkPlugins!, [remarkPaperLocators,{paperId}]] : markdownRemarkPlugins, [paperId,onPdfPage]);
  return <div className="prose-chat markdown-content">
    <ReactMarkdown
      remarkPlugins={plugins}
      rehypePlugins={markdownRehypePlugins}
      skipHtml
      components={{
        img: ({ node: _node, ...props }) => images ? <img {...props} /> : null,
        a: ({ node: _node, ...props }) => {
          const target=pdfLocatorTarget(props.href);
          if(onPdfPage&&target&&target.paperId===paperId)return <a {...props} onClick={e=>{e.preventDefault();onPdfPage(target.paperId,target.page);}}/>;
          return onPaperCitation && props.href?.startsWith('#pm-paper-') ? <a {...props} onClick={e=>{e.preventDefault();onPaperCitation(Number(props.href!.slice(10)));}}/> : <a {...props} target="_blank" rel="noopener noreferrer" />;
        },
        table: ({ node: _node, ...props }) => <div className="markdown-table-scroll" tabIndex={0} role="region" aria-label="表格，可横向滚动"><table {...props} /></div>,
      }}
    >{markdown}</ReactMarkdown>
  </div>;
});
