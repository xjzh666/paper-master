import { useEffect, useRef } from 'react'
import { Spin, Alert, Typography, Anchor, Empty, Collapse, message } from 'antd'
import ReactMarkdown from 'react-markdown'
import GithubSlugger from 'github-slugger'
import { remarkPlugins, rehypePlugins } from '../markdown/plugins'
import { locateCiteTargets } from '../citation'
import type { PaperOverview, ChunkIndexEntry } from '../api/client'
import '../cite-highlight.css'

interface Props {
  status: string
  error: string
  overview: PaperOverview | null
  markdown: string
  /** 一次性引用点击事件：seq 递增保证重复点击同一 chunk 也重触发 */
  citeTarget?: { chunkId: string; seq: number } | null
  /** chunks 索引（GET /api/papers/{id}/chunks-index），null/undefined 表示未就绪 */
  chunkIndex?: ChunkIndexEntry[] | null
}

export default function ReadingPanel({ status, error, overview, markdown, citeTarget, chunkIndex }: Props) {
  const bodyRef = useRef<HTMLDivElement | null>(null)

  // citeTarget（seq 递增）触发定位：按 chunk snippets 在已渲染 DOM 中匹配，
  // 命中 → 滚到第一个命中块 + 全部命中块 3s 高亮；未命中 → message 提示，不滚动。
  // 每轮 effect 自带 cleanup：再次触发/卸载时先清理上一轮高亮类与定时器（不叠加、不泄漏）。
  useEffect(() => {
    if (!citeTarget) return
    const entry = chunkIndex?.find((c) => c.id === citeTarget.chunkId)
    const body = bodyRef.current
    if (!entry || !body) {
      message.info('未在原文中定位到该片段')
      return
    }
    const hits = locateCiteTargets(body, entry.snippets)
    if (hits.length === 0) {
      message.info('未在原文中定位到该片段')
      return
    }
    hits.forEach((el) => el.classList.add('cite-flash'))
    hits[0].scrollIntoView({ behavior: 'smooth', block: 'start' })
    const timer = window.setTimeout(() => {
      hits.forEach((el) => el.classList.remove('cite-flash'))
    }, 3000)
    return () => {
      window.clearTimeout(timer)
      hits.forEach((el) => el.classList.remove('cite-flash'))
    }
    // 依赖只用 seq：citeTarget 是一次性事件（seq 递增触发）；触发时 chunkIndex/markdown 已就绪
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [citeTarget?.seq])

  if (status === 'parsing') {
    return (
      <div style={{ padding: 48, textAlign: 'center' }}>
        <Spin size="large" tip="正在解析论文 (MinerU)..." />
      </div>
    )
  }
  if (status === 'error') {
    return <Alert type="error" message="解析失败" description={error} showIcon />
  }
  if (!overview) return <Empty description="从左侧选择一篇论文" />

  const slugger = new GithubSlugger()
  const tocItems = overview.toc.map((s) => ({
    key: s.title,
    href: `#${slugger.slug(s.title)}`,
    title: s.title,
  }))

  return (
    <div>
      <Typography.Title level={4}>{overview.title}</Typography.Title>
      {overview.abstract && (
        <Typography.Paragraph type="secondary" style={{ whiteSpace: 'pre-wrap' }}>
          {overview.abstract}
        </Typography.Paragraph>
      )}
      {tocItems.length > 0 && (
        <Collapse
          size="small"
          style={{ marginBottom: 8 }}
          items={[{
            key: 'toc',
            label: `目录 (${tocItems.length})`,
            children: <Anchor items={tocItems} />,
          }]}
        />
      )}
      <div className="markdown-body" ref={bodyRef}>
        <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins}>
          {markdown}
        </ReactMarkdown>
      </div>
    </div>
  )
}
