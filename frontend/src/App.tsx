import { useState, useRef } from 'react'
import { Layout, message } from 'antd'
import PaperListSidebar from './components/PaperListSidebar'
import ChatPanel from './components/ChatPanel'
import ReadingPanel from './components/ReadingPanel'
import { api } from './api/client'
import type { PaperOverview, ZoteroItem, ChunkIndexEntry } from './api/client'

const { Sider, Content } = Layout

/** 一次性引用点击事件：seq 递增保证重复点击同一 chunk 也重触发（消费方不重放） */
interface CiteTarget {
  chunkId: string
  seq: number
}

export default function App() {
  const [paperId, setPaperId] = useState<string | null>(null)
  const [status, setStatus] = useState<'idle' | 'parsing' | 'ready' | 'error'>('idle')
  const [error, setError] = useState('')
  const [overview, setOverview] = useState<PaperOverview | null>(null)
  const [markdown, setMarkdown] = useState('')
  const [chunkIndex, setChunkIndex] = useState<ChunkIndexEntry[] | null>(null)
  // citeTarget 由 ReadingPanel 消费（引用定位高亮，Task 6）
  const [citeTarget, setCiteTarget] = useState<CiteTarget | null>(null)
  const pollRef = useRef<number | null>(null)
  const paperIdRef = useRef<string | null>(null)
  const citeSeqRef = useRef(0)

  const loadReady = async (pid: string) => {
    if (paperIdRef.current !== pid) return
    const [ov, ct, ci] = await Promise.all([
      api.overview(pid),
      api.content(pid),
      api.chunksIndex(pid).catch(() => null), // 索引拉取失败降级为「未就绪」，不阻塞论文加载
    ])
    if (paperIdRef.current !== pid) return
    setOverview(ov)
    setMarkdown(ct.markdown)
    setChunkIndex(ci ? ci.chunks : null)
    setStatus('ready')
  }

  const openPaper = async (item: ZoteroItem) => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
    setPaperId(null)
    setOverview(null)
    setMarkdown('')
    setError('')
    setChunkIndex(null)
    setCiteTarget(null)
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

  const handleCite = (chunkId: string) => {
    if (!chunkIndex) {
      message.info('原文索引尚未就绪')
      return
    }
    citeSeqRef.current += 1
    setCiteTarget({ chunkId, seq: citeSeqRef.current })
  }

  return (
    <Layout style={{ height: '100vh' }}>
      <Sider width={320} theme="light" style={{ borderRight: '1px solid #eee', overflow: 'auto' }}>
        <PaperListSidebar onOpen={openPaper} />
      </Sider>
      <Content style={{ padding: 16, borderRight: '1px solid #eee' }}>
        <ChatPanel paperId={paperId} disabled={status !== 'ready'} onCite={handleCite} />
      </Content>
      <Sider width={560} theme="light" style={{ padding: 16, overflow: 'auto' }}>
        <ReadingPanel
          status={status}
          error={error}
          overview={overview}
          markdown={markdown}
          citeTarget={citeTarget}
          chunkIndex={chunkIndex}
        />
      </Sider>
    </Layout>
  )
}
