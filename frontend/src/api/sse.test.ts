import { describe, it, expect } from 'vitest'
import { parseFrame } from './sse'

describe('parseFrame', () => {
  it('parses answer_chunk', () => {
    expect(parseFrame('event: answer_chunk\ndata: {"delta":"你好"}'))
      .toEqual({ type: 'answer_chunk', delta: '你好' })
  })
  it('parses tool_start', () => {
    expect(parseFrame('event: tool_start\ndata: {"name":"search_paper","arguments":"{\\"query\\":\\"x\\"}"}'))
      .toEqual({ type: 'tool_start', name: 'search_paper', arguments: '{"query":"x"}' })
  })
  it('parses clear and done', () => {
    expect(parseFrame('event: clear\ndata: {}')).toEqual({ type: 'clear' })
    expect(parseFrame('event: done\ndata: {}')).toEqual({ type: 'done' })
  })
  it('returns null for empty data', () => {
    expect(parseFrame('event: ping\ndata:')).toBeNull()
  })
})
