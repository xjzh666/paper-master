import { useEffect, useState } from 'react'
import { Tree, Input, List, Typography, Tag, Spin, Empty, Tabs, message } from 'antd'
import type { DataNode } from 'antd/es/tree'
import type { ZoteroCollection, ZoteroItem, ArxivResult } from '../api/client'
import { api } from '../api/client'

interface Props {
  onOpen: (item: ZoteroItem) => void
  onOpenArxiv: (item: ArxivResult) => void
}

/** 摘要截断长度（列表内单条不占满屏） */
const ABSTRACT_MAX = 160

export default function PaperListSidebar({ onOpen, onOpenArxiv }: Props) {
  return (
    <div style={{ padding: 12, height: '100%' }}>
      <Tabs
        defaultActiveKey="zotero"
        items={[
          { key: 'zotero', label: 'Zotero 论文库', children: <ZoteroPane onOpen={onOpen} /> },
          { key: 'arxiv', label: 'arXiv 搜索', children: <ArxivPane onOpenArxiv={onOpenArxiv} /> },
        ]}
      />
    </div>
  )
}

function ZoteroPane({ onOpen }: { onOpen: (item: ZoteroItem) => void }) {
  const [collections, setCollections] = useState<ZoteroCollection[]>([])
  const [items, setItems] = useState<ZoteroItem[]>([])
  const [loading, setLoading] = useState(false)

  const loadItems = async (collectionId?: number, q?: string) => {
    setLoading(true)
    try {
      setItems(q ? await api.search(q) : await api.items(collectionId))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    api.collections().then(setCollections).catch(() => {})
    loadItems()
  }, [])

  const treeData: DataNode[] = collections
    .filter((c) => c.parent_id === null)
    .map((c) => ({
      key: c.collection_id,
      title: `${c.name} (${c.item_count})`,
      children: collections
        .filter((x) => x.parent_id === c.collection_id)
        .map((x) => ({ key: x.collection_id, title: `${x.name} (${x.item_count})` })),
    }))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <Input.Search
        placeholder="搜索论文"
        allowClear
        onSearch={(v) => loadItems(undefined, v)}
      />
      <Tree
        treeData={treeData}
        defaultExpandAll
        onSelect={(keys) => {
          if (keys[0] !== undefined) loadItems(Number(keys[0]))
        }}
      />
      <div style={{ flex: 1, overflow: 'auto' }}>
        <Spin spinning={loading}>
          {items.length === 0 ? (
            <Empty description="无论文" />
          ) : (
            <List
              size="small"
              dataSource={items}
              renderItem={(it) => (
                <List.Item style={{ cursor: 'pointer' }} onClick={() => onOpen(it)}>
                  <div style={{ width: '100%' }}>
                    <Typography.Text ellipsis>{it.title}</Typography.Text>
                    <div>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {it.creators.slice(0, 3).join(', ')} {it.year ?? ''}
                      </Typography.Text>
                      {it.has_pdf ? <Tag color="green">PDF</Tag> : <Tag>无 PDF</Tag>}
                    </div>
                  </div>
                </List.Item>
              )}
            />
          )}
        </Spin>
      </div>
    </div>
  )
}

function ArxivPane({ onOpenArxiv }: { onOpenArxiv: (item: ArxivResult) => void }) {
  const [results, setResults] = useState<ArxivResult[]>([])
  const [source, setSource] = useState<'arxiv' | 'openalex' | 's2'>('arxiv')
  const [loading, setLoading] = useState(false)

  const doSearch = async (q: string) => {
    if (!q) return
    setLoading(true)
    try {
      const res = await api.arxivSearch(q)
      setResults(res.results)
      setSource(res.source ?? 'arxiv') // 缺失视为 arxiv
    } catch (e) {
      // 错误文案来自后端 detail（"外部检索失败: ..."）
      message.error(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <Input.Search
        placeholder="搜索 arXiv 论文"
        allowClear
        onSearch={doSearch}
      />
      <div style={{ flex: 1, overflow: 'auto' }}>
        {source === 'openalex' && <Tag color="orange">OpenAlex 兜底</Tag>}
        {source === 's2' && <Tag color="blue">Semantic Scholar</Tag>}
        <Spin spinning={loading}>
          {results.length === 0 ? (
            <Empty description="无论文" />
          ) : (
            <List
              size="small"
              dataSource={results}
              renderItem={(r) => (
                <List.Item style={{ cursor: 'pointer' }} onClick={() => onOpenArxiv(r)}>
                  <div style={{ width: '100%' }}>
                    <Typography.Text ellipsis>{r.title}</Typography.Text>
                    <div>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {r.authors.slice(0, 3).join(', ')} {r.published.slice(0, 4)}
                        {r.citation_count != null && ` · 被引 ${r.citation_count}`}
                      </Typography.Text>
                      <Tag color="blue">{r.arxiv_id}</Tag>
                    </div>
                    <Typography.Paragraph
                      type="secondary"
                      style={{ fontSize: 12, marginBottom: 0 }}
                      ellipsis
                    >
                      {r.abstract.length > ABSTRACT_MAX
                        ? `${r.abstract.slice(0, ABSTRACT_MAX)}…`
                        : r.abstract}
                    </Typography.Paragraph>
                  </div>
                </List.Item>
              )}
            />
          )}
        </Spin>
      </div>
    </div>
  )
}
