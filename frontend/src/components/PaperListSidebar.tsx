import { useEffect, useState } from 'react'
import { Tree, Input, List, Typography, Tag, Spin, Empty } from 'antd'
import type { DataNode } from 'antd/es/tree'
import type { ZoteroCollection, ZoteroItem } from '../api/client'
import { api } from '../api/client'

interface Props {
  onOpen: (item: ZoteroItem) => void
}

export default function PaperListSidebar({ onOpen }: Props) {
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
    <div style={{ padding: 12, height: '100%', display: 'flex', flexDirection: 'column', gap: 8 }}>
      <Typography.Title level={5} style={{ margin: 0 }}>Zotero 论文库</Typography.Title>
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
