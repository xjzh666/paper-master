import { useState } from 'react'
import { Input, List, Typography, Collapse, Tag, Empty, Space } from 'antd'
import { postChatSSE } from '../api/sse'

interface Props {
  paperId: string | null
  disabled: boolean
}

interface Msg {
  role: 'user' | 'assistant'
  content: string
}

interface ToolLog {
  name: string
  args: string
  chars: number
}

export default function ChatPanel({ paperId, disabled }: Props) {
  const [messages, setMessages] = useState<Msg[]>([])
  const [toolLog, setToolLog] = useState<ToolLog[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)

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
      <Typography.Title level={5}>对话</Typography.Title>
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
            renderItem={(m) => (
              <List.Item style={{ justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
                <Typography.Paragraph
                  style={{
                    maxWidth: '80%',
                    whiteSpace: 'pre-wrap',
                    background: m.role === 'user' ? '#e6f4ff' : '#f5f5f5',
                    padding: 8,
                    borderRadius: 8,
                    margin: 0,
                  }}
                >
                  {m.content || (busy ? '思考中...' : '')}
                </Typography.Paragraph>
              </List.Item>
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
