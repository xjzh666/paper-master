import { describe, it, expect, vi, afterEach } from 'vitest'
import { api, type ChunkIndexEntry, type ArxivResult } from './client'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('api.chunksIndex', () => {
  it('GETs /api/papers/{paperId}/chunks-index and returns the JSON payload', async () => {
    const payload = {
      chunks: [
        {
          id: 'chunk_12',
          page: 4,
          section: '3.2 System Model',
          snippets: ['We model the system as a set of parties.'],
        },
      ],
    }
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => payload }))
    vi.stubGlobal('fetch', fetchMock)

    const res = await api.chunksIndex('deadbeef')

    expect(fetchMock).toHaveBeenCalledWith('/api/papers/deadbeef/chunks-index')
    const entries: ChunkIndexEntry[] = res.chunks
    expect(entries).toEqual(payload.chunks)
  })

  it('throws on non-2xx status', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404 })))
    await expect(api.chunksIndex('missing')).rejects.toThrow('404')
  })
})

describe('api.arxivSearch', () => {
  it('GETs /api/arxiv/search?q=<encoded> and returns the results payload', async () => {
    const payload = { results: [ARXIV_RESULT] }
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => payload }))
    vi.stubGlobal('fetch', fetchMock)

    const res = await api.arxivSearch('attention is all you need')

    expect(fetchMock).toHaveBeenCalledWith('/api/arxiv/search?q=attention%20is%20all%20you%20need')
    const results: ArxivResult[] = res.results
    expect(results).toEqual(payload.results)
  })

  it('appends max_results when provided', async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ results: [] }) }))
    vi.stubGlobal('fetch', fetchMock)

    await api.arxivSearch('graph', 5)

    expect(fetchMock).toHaveBeenCalledWith('/api/arxiv/search?q=graph&max_results=5')
  })

  it('passes through the source field when present (openalex fallback marker)', async () => {
    const payload = { results: [ARXIV_RESULT], source: 'openalex' as const }
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => payload })))

    const res = await api.arxivSearch('attention is all you need')

    expect(res.source).toBe('openalex')
  })
})

describe('api.openArxivPaper', () => {
  it('POSTs {"arxiv_id": id} to /api/arxiv/open and returns OpenResult on ok', async () => {
    const open = { paper_id: 'deadbeef', status: 'ready' }
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => ({ ok: true, json: async () => open }))
    vi.stubGlobal('fetch', fetchMock)

    const res = await api.openArxivPaper('1706.03762')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/arxiv/open')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(String(init?.body))).toEqual({ arxiv_id: '1706.03762' })
    expect(res).toEqual(open)
  })

  it('throws Error(body.detail) on non-ok (502 下载失败不被当成功)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 502,
        json: async () => ({ detail: 'arXiv PDF 下载失败: connection reset' }),
      })),
    )
    await expect(api.openArxivPaper('1706.03762')).rejects.toThrow(
      'arXiv PDF 下载失败: connection reset',
    )
  })
})

const ARXIV_RESULT: ArxivResult = {
  arxiv_id: '1706.03762',
  title: 'Attention Is All You Need',
  authors: ['Ashish Vaswani', 'Noam Shazeer', 'Niki Parmar', 'Jakob Uszkoreit'],
  abstract: 'The dominant sequence transduction models are based on recurrent networks.',
  published: '2017-06-07T17:57:34Z',
  updated: '2017-06-12T23:41:29Z',
  categories: ['cs.CL'],
  pdf_url: 'https://arxiv.org/pdf/1706.03762',
  abs_url: 'https://arxiv.org/abs/1706.03762',
}
