import { memo, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import { markdownRehypePlugins, markdownRemarkPlugins, normalizeMathDelimiters } from '../pages/markdownModel';
import 'katex/dist/katex.min.css';
import './markdown.css';

/** One renderer for both sides of the conversation, including streamed replies. */
export const MarkdownContent = memo(function MarkdownContent({ content }: { content: string }) {
  const markdown = useMemo(() => normalizeMathDelimiters(content), [content]);
  return <div className="prose-chat markdown-content">
    <ReactMarkdown
      remarkPlugins={markdownRemarkPlugins}
      rehypePlugins={markdownRehypePlugins}
      skipHtml
      components={{
        a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
        table: ({ node: _node, ...props }) => <div className="markdown-table-scroll" tabIndex={0} role="region" aria-label="表格，可横向滚动"><table {...props} /></div>,
      }}
    >{markdown}</ReactMarkdown>
  </div>;
});
