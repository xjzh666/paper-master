import { Spin, Alert, Typography, Anchor, Empty, Collapse } from 'antd'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import rehypeRaw from 'rehype-raw'
import rehypeSlug from 'rehype-slug'
import rehypeMathInHtml from '../markdown/rehypeMathInHtml'
import GithubSlugger from 'github-slugger'
import type { PaperOverview } from '../api/client'

interface Props {
  status: string
  error: string
  overview: PaperOverview | null
  markdown: string
}

export default function ReadingPanel({ status, error, overview, markdown }: Props) {
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
      <div className="markdown-body">
        <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeSlug, rehypeKatex, rehypeRaw, rehypeMathInHtml]}>
          {markdown}
        </ReactMarkdown>
      </div>
    </div>
  )
}
