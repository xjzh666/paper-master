import { Fragment, memo, useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { Button, Divider, Input, List, Typography, Collapse, Tag, Empty, Space } from 'antd'
import { postChatSSE } from '../api/sse'
import { api, type ChatMessage } from '../api/client'
import { remarkPlugins, rehypePlugins } from '../markdown/plugins'

interface Props {
  paperId: string | null
  disabled: boolean
}

interface ToolLog {
  name: string
  args: string
  chars: number
}

const MarkdownMessage = memo(function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="markdown-body" style={{ fontSize: 14 }}>
      <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins}>
        {content}
      </ReactMarkdown>
    </div>
  )
})

export default function ChatPanel({ paperId, disabled }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [historyCount, setHistoryCount] = useState(0)
  const [toolLog, setToolLog] = useState<ToolLog[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setMessages([])
    setHistoryCount(0)
    setToolLog([])
    if (!paperId) return
    let stale = false
    api.history(paperId)
      .then((r) => {
        if (stale) return
        setMessages(r.messages)
        setHistoryCount(r.messages.length)
      })
      .catch(() => {})
    return () => { stale = true }
  }, [paperId])

  const clearHistory = async () => {
    if (!paperId || busy) return
    try {
      await api.clearHistory(paperId)
      setMessages([])
      setHistoryCount(0)
      setToolLog([])
    } catch {
      /* 删除失败则保留现状 */
    }
  }

  const patchLastAnswer = (text: string) => {
    setMessages((m) => {
      const next = [...m]
      next[next.length - 1] = { role: 'assistant', content: text }
      return next
    })
  }

  const send = async () => {
    const q = input.trim()
    if (!q || !paperId || busy) return
    setInput('')
    setMessages((m) => [...m, { role: 'user', content: q }])
    setMessages((m) => [...m, { role: 'assistant', content: '' }])
    setBusy(true)
    let buffer = ''
    try {
      await postChatSSE(paperId, q, (ev) => {
        if (ev.type === 'tool_start') {
          setToolLog((t) => [...t, { name: ev.name, args: ev.arguments, chars: 0 }])
        } else if (ev.type === 'tool_result') {
          setToolLog((t) => {
            const next = [...t]
            if (next.length) next[next.length - 1] = { ...next[next.length - 1], chars: ev.chars }
            return next
          })
        } else if (ev.type === 'answer_chunk') {
          buffer += ev.delta
          patchLastAnswer(buffer)
        } else if (ev.type === 'clear') {
          buffer = ''
          patchLastAnswer('')
        } else if (ev.type === 'error') {
          patchLastAnswer(`[错误] ${ev.message}`)
        }
      })
    } catch (e) {
      patchLastAnswer(`[网络错误] ${String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography.Title level={5}>对话</Typography.Title>
        {messages.length > 0 && (
          <Button size="small" type="text" danger onClick={clearHistory}>
            清空
          </Button>
        )}
      </div>
      {toolLog.length > 0 && (
        <Collapse
          size="small"
          items={[{
            key: 'log',
            label: `检索过程 (${toolLog.length} 步)`,
            children: (
              <List
                size="small"
                dataSource={toolLog}
                renderItem={(t) => (
                  <List.Item>
                    <Space>
                      <Tag>{t.name}</Tag>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {t.args.slice(0, 80)}
                      </Typography.Text>
                      {t.chars > 0 && <Tag>{t.chars} chars</Tag>}
                    </Space>
                  </List.Item>
                )}
              />
            ),
          }]}
        />
      )}
      <div style={{ flex: 1, overflow: 'auto', margin: '8px 0' }}>
        {messages.length === 0 ? (
          <Empty description="选一篇论文，开始提问" />
        ) : (
          <List
            dataSource={messages}
            renderItem={(m, i) => (
              <Fragment key={i}>
                {historyCount > 0 && i === historyCount && (
                  <Divider plain style={{ fontSize: 12, color: '#999', margin: '4px 0' }}>
                    以上是历史对话
                  </Divider>
                )}
                <List.Item style={{ justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
                {m.role === 'assistant' ? (
                  <div
                    style={{
                      maxWidth: '90%',
                      background: '#f5f5f5',
                      padding: 8,
                      borderRadius: 8,
                    }}
                  >
                    {m.content ? (
                      <MarkdownMessage content={m.content} />
                    ) : (
                      <Typography.Text type="secondary">{busy ? '思考中...' : ''}</Typography.Text>
                    )}
                  </div>
                ) : (
                  <Typography.Paragraph
                    style={{
                      maxWidth: '80%',
                      whiteSpace: 'pre-wrap',
                      background: '#e6f4ff',
                      padding: 8,
                      borderRadius: 8,
                      margin: 0,
                    }}
                  >
                    {m.content}
                  </Typography.Paragraph>
                )}
              </List.Item>
              </Fragment>
            )}
          />
        )}
      </div>
      <Input.Search
        placeholder="对这篇论文提问…"
        enterButton="发送"
        value={input}
        disabled={disabled || busy}
        onChange={(e) => setInput(e.target.value)}
        onSearch={send}
      />
    </div>
  )
}
