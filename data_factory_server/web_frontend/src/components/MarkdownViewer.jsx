import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Card } from 'antd'

/**
 * Markdown 查看器组件
 * 
 * 用于显示 README.md 等内容，支持代码块、表格等markdown格式
 */
const MarkdownViewer = ({ content }) => {
  return (
    <Card>
      <div 
        className="markdown-content"
        style={{ 
          maxWidth: '1200px', 
          margin: '0 auto',
          padding: '20px',
        }}
      >
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            // 代码块样式
            code({ node, inline, className, children, ...props }) {
              const match = /language-(\w+)/.exec(className || '')
              return !inline && match ? (
                <pre
                  style={{
                    background: '#f5f5f5',
                    padding: '16px',
                    borderRadius: '4px',
                    overflow: 'auto',
                    fontSize: '14px',
                    lineHeight: '1.5',
                    margin: '16px 0',
                  }}
                >
                  <code className={className} {...props}>
                    {children}
                  </code>
                </pre>
              ) : (
                <code
                  className={className}
                  style={{
                    background: '#f5f5f5',
                    padding: '2px 6px',
                    borderRadius: '3px',
                    fontSize: '0.9em',
                    fontFamily: 'monospace',
                  }}
                  {...props}
                >
                  {children}
                </code>
              )
            },
            // 表格样式
            table({ children }) {
              return (
                <div style={{ overflowX: 'auto', margin: '16px 0' }}>
                  <table
                    style={{
                      width: '100%',
                      borderCollapse: 'collapse',
                      border: '1px solid #d9d9d9',
                    }}
                  >
                    {children}
                  </table>
                </div>
              )
            },
            thead({ children }) {
              return (
                <thead
                  style={{
                    background: '#fafafa',
                    fontWeight: 'bold',
                  }}
                >
                  {children}
                </thead>
              )
            },
            tbody({ children }) {
              return <tbody>{children}</tbody>
            },
            tr({ children }) {
              return (
                <tr
                  style={{
                    borderBottom: '1px solid #d9d9d9',
                  }}
                >
                  {children}
                </tr>
              )
            },
            th({ children }) {
              return (
                <th
                  style={{
                    padding: '12px',
                    textAlign: 'left',
                    border: '1px solid #d9d9d9',
                  }}
                >
                  {children}
                </th>
              )
            },
            td({ children }) {
              return (
                <td
                  style={{
                    padding: '12px',
                    border: '1px solid #d9d9d9',
                  }}
                >
                  {children}
                </td>
              )
            },
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
    </Card>
  )
}

export default MarkdownViewer

