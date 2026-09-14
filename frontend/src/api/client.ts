export interface ZoteroCollection {
  collection_id: number
  name: string
  parent_id: number | null
  item_count: number
}

export interface ZoteroItem {
  item_id: number
  title: string
  creators: string[]
  year: number | null
  journal: string | null
  collections: string[]
  has_pdf: boolean
  pdf_path: string | null
  doi: string | null
}

export interface PaperOverview {
  title: string
  abstract: string
  toc: { title: string; level: number }[]
}

export interface OpenResult {
  paper_id: string
  status: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ParseStatus {
  status: string
  message?: string
}

export interface ChunkIndexEntry {
  id: string
  page: number
  section: string
  snippets: string[]
}

/** 一条 arXiv 检索结果（9 字段与后端 arxiv_search.ArxivResult dataclass 对齐） */
export interface ArxivResult {
  arxiv_id: string
  title: string
  authors: string[]
  abstract: string
  published: string
  updated: string
  categories: string[]
  pdf_url: string
  abs_url: string
}

async function get<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`GET ${url} → ${res.status}`)
  return res.json() as Promise<T>
}

export const api = {
  collections: () => get<ZoteroCollection[]>('/api/zotero/collections'),
  items: (collectionId?: number) =>
    get<ZoteroItem[]>(`/api/zotero/items${collectionId ? `?collection_id=${collectionId}` : ''}`),
  search: (q: string) =>
    get<ZoteroItem[]>(`/api/zotero/search?q=${encodeURIComponent(q)}`),
  arxivSearch: async (q: string, maxResults?: number) => {
    const url = `/api/arxiv/search?q=${encodeURIComponent(q)}${maxResults ? `&max_results=${maxResults}` : ''}`
    const res = await fetch(url)
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: `GET ${url} → ${res.status}` }))
      throw new Error(body.detail) // 错误文案对齐后端 detail（"外部检索失败: ..."）
    }
    // source 标识结果来源；缺失视为 'arxiv'（旧后端兼容）
    return res.json() as Promise<{ results: ArxivResult[]; source?: 'arxiv' | 'openalex' }>
  },
  openArxivPaper: (arxivId: string) =>
    fetch('/api/arxiv/open', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ arxiv_id: arxivId }),
    }).then(async (res) => {
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: `POST /api/arxiv/open → ${res.status}` }))
        throw new Error(body.detail) // 502/400/500 的 detail 直接抛出，不能当成功
      }
      return res.json() as Promise<OpenResult>
    }),
  openPaper: (zoteroItemId: number) =>
    fetch('/api/papers/open', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ zotero_item_id: zoteroItemId }),
    }).then((r) => r.json() as Promise<OpenResult>),
  paperStatus: (paperId: string) => get<ParseStatus>(`/api/papers/${paperId}/status`),
  overview: (paperId: string) => get<PaperOverview>(`/api/papers/${paperId}/overview`),
  content: (paperId: string) => get<{ markdown: string }>(`/api/papers/${paperId}/content`),
  chunksIndex: (paperId: string) =>
    get<{ chunks: ChunkIndexEntry[] }>(`/api/papers/${paperId}/chunks-index`),
  history: (paperId: string) =>
    get<{ messages: ChatMessage[] }>(`/api/papers/${paperId}/history`),
  clearHistory: (paperId: string) =>
    fetch(`/api/papers/${paperId}/history`, { method: 'DELETE' }).then((r) => {
      if (!r.ok) throw new Error(`DELETE /api/papers/${paperId}/history → ${r.status}`)
    }),
}
