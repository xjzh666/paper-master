import { useState, useRef } from 'react'
import { Layout } from 'antd'
import PaperListSidebar from './components/PaperListSidebar'
import ChatPanel from './components/ChatPanel'
import ReadingPanel from './components/ReadingPanel'
import { api } from './api/client'
import type { PaperOverview, ZoteroItem } from './api/client'

const { Sider, Content } = Layout

export default function App() {
  const [paperId, setPaperId] = useState<string | null>(null)
  const [status, setStatus] = useState<'idle' | 'parsing' | 'ready' | 'error'>('idle')
  const [error, setError] = useState('')
  const [overview, setOverview] = useState<PaperOverview | null>(null)
  const [markdown, setMarkdown] = useState('')
  const pollRef = useRef<number | null>(null)
  const paperIdRef = useRef<string | null>(null)

  const loadReady = async (pid: string) => {
    if (paperIdRef.current !== pid) return
    const [ov, ct] = await Promise.all([api.overview(pid), api.content(pid)])
    if (paperIdRef.current !== pid) return
    setOverview(ov)
    setMarkdown(ct.markdown)
    setStatus('ready')
  }

  const openPaper = async (item: ZoteroItem) => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
    setPaperId(null)
    setOverview(null)
    setMarkdown('')
    setError('')
    setStatus('parsing')
    try {
      const res = await api.openPaper(item.item_id)
      setPaperId(res.paper_id)
      paperIdRef.current = res.paper_id
      if (res.status === 'ready') {
        await loadReady(res.paper_id)
      } else {
        pollStatus(res.paper_id)
      }
    } catch (e) {
      setError(String(e))
      setStatus('error')
    }
  }

  const pollStatus = (pid: string) => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = window.setInterval(async () => {
      try {
        const st = await api.paperStatus(pid)
        if (paperIdRef.current !== pid) return
        if (st.status === 'ready') {
          if (pollRef.current) clearInterval(pollRef.current)
          pollRef.current = null
          await loadReady(pid)
        } else if (st.status === 'error') {
          if (pollRef.current) clearInterval(pollRef.current)
          pollRef.current = null
          if (paperIdRef.current === pid) {
            setError(st.message ?? '解析失败')
            setStatus('error')
          }
        }
      } catch {
        // keep polling
      }
    }, 2000)
  }

  return (
    <Layout style={{ height: '100vh' }}>
      <Sider width={320} theme="light" style={{ borderRight: '1px solid #eee', overflow: 'auto' }}>
        <PaperListSidebar onOpen={openPaper} />
      </Sider>
      <Content style={{ padding: 16, borderRight: '1px solid #eee' }}>
        <ChatPanel paperId={paperId} disabled={status !== 'ready'} />
      </Content>
      <Sider width={560} theme="light" style={{ padding: 16, overflow: 'auto' }}>
        <ReadingPanel status={status} error={error} overview={overview} markdown={markdown} />
      </Sider>
    </Layout>
  )
}
