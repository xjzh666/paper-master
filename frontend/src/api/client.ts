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

export interface ParseStatus {
  status: string
  message?: string
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
  openPaper: (zoteroItemId: number) =>
    fetch('/api/papers/open', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ zotero_item_id: zoteroItemId }),
    }).then((r) => r.json() as Promise<OpenResult>),
  paperStatus: (paperId: string) => get<ParseStatus>(`/api/papers/${paperId}/status`),
  overview: (paperId: string) => get<PaperOverview>(`/api/papers/${paperId}/overview`),
  content: (paperId: string) => get<{ markdown: string }>(`/api/papers/${paperId}/content`),
}
