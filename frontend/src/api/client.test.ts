import { describe, it, expect, vi, afterEach } from 'vitest'
import { api, type ChunkIndexEntry } from './client'

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
