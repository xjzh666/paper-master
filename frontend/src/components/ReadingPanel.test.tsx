// @vitest-environment jsdom
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react'
import { message } from 'antd'
import ReadingPanel from './ReadingPanel'
import type { PaperOverview, ChunkIndexEntry } from '../api/client'

vi.mock('antd', async (importOriginal) => {
  const actual = await importOriginal<typeof import('antd')>()
  return { ...actual, message: { ...actual.message, info: vi.fn() } }
})

const OVERVIEW: PaperOverview = { title: 'Test Paper', abstract: '', toc: [] }

const MD = [
  '# Intro',
  '',
  'Paragraph text about the system model.',
  '',
  '- item one text',
  '- item two text',
  '',
  '## Method',
  '',
  'Method paragraph describing training.',
  '',
  'While for small values of $d_{k}$ the two attentions perform similarly.',
].join('\n')

const CHUNKS: ChunkIndexEntry[] = [
  { id: 'chunk_1', page: 3, section: 'Intro', snippets: ['Paragraph text about the system', 'item one text'] },
  { id: 'chunk_2', page: 5, section: 'Method', snippets: ['Method paragraph describing'] },
  { id: 'chunk_3', page: 7, section: 'Method', snippets: ['for small values of d_{k} the two'] },
]

const NO_HIT_MSG = '未在原文中定位到该片段'

let container: HTMLDivElement
let root: Root

beforeAll(() => {
  ;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  // jsdom 未实现 matchMedia；antd 组件树渲染可能依赖
  if (!window.matchMedia) {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: (query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }),
    })
  }
})

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  // jsdom 没有 scrollIntoView，stub 到原型上
  Element.prototype.scrollIntoView = vi.fn()
})

afterEach(() => {
  act(() => {
    root.unmount()
  })
  container.remove()
  delete (Element.prototype as { scrollIntoView?: () => void }).scrollIntoView
  vi.clearAllMocks()
  vi.useRealTimers()
})

async function renderPanel(
  props: { citeTarget?: { chunkId: string; seq: number } | null; chunkIndex?: ChunkIndexEntry[] | null } = {},
) {
  await act(async () => {
    root.render(<ReadingPanel status="ready" error="" overview={OVERVIEW} markdown={MD} {...props} />)
  })
}

function findP(text: string): HTMLParagraphElement {
  const p = [...container.querySelectorAll('p')].find((el) => el.textContent?.includes(text))
  expect(p, `paragraph containing "${text}"`).toBeDefined()
  return p as HTMLParagraphElement
}

function findLi(text: string): HTMLLIElement {
  const li = [...container.querySelectorAll('li')].find((el) => el.textContent?.includes(text))
  expect(li, `li containing "${text}"`).toBeDefined()
  return li as HTMLLIElement
}

describe('ReadingPanel 引用定位', () => {
  it('缺省 props：行为与现状一致（正常渲染，无提示无高亮无滚动）', async () => {
    await renderPanel()
    expect(findP('Paragraph text about the system model.')).toBeTruthy()
    expect(container.querySelector('.cite-flash')).toBeNull()
    expect(message.info).not.toHaveBeenCalled()
    expect(vi.mocked(Element.prototype.scrollIntoView)).not.toHaveBeenCalled()
  })

  it('citeTarget 命中：第一个命中元素 scrollIntoView({smooth,start}) 一次，全部命中块加 cite-flash，3000ms 后移除', async () => {
    vi.useFakeTimers()
    // 先渲染正文，再对目标元素打元素级 spy（React 重渲染复用同一 DOM 节点）
    await renderPanel({ chunkIndex: CHUNKS })
    const p = findP('Paragraph text about the system model.')
    const li = findLi('item one text')
    const ownSpy = vi.fn()
    p.scrollIntoView = ownSpy as unknown as Element['scrollIntoView']

    await renderPanel({ chunkIndex: CHUNKS, citeTarget: { chunkId: 'chunk_1', seq: 1 } })

    // scrollIntoView 恰在第一个命中元素（p，snippet 顺序第一）上调用一次，参数正确
    expect(ownSpy).toHaveBeenCalledTimes(1)
    expect(ownSpy).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' })
    expect(vi.mocked(Element.prototype.scrollIntoView)).not.toHaveBeenCalled()
    // 全部命中块加高亮类
    expect(p.classList.contains('cite-flash')).toBe(true)
    expect(li.classList.contains('cite-flash')).toBe(true)
    expect(container.querySelectorAll('.cite-flash')).toHaveLength(2)
    // 2999ms 仍高亮，3000ms 移除
    act(() => {
      vi.advanceTimersByTime(2999)
    })
    expect(p.classList.contains('cite-flash')).toBe(true)
    expect(li.classList.contains('cite-flash')).toBe(true)
    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(p.classList.contains('cite-flash')).toBe(false)
    expect(li.classList.contains('cite-flash')).toBe(false)
  })

  it('重复触发：先清理上一轮高亮与定时器，不叠加不泄漏', async () => {
    vi.useFakeTimers()
    await renderPanel({ chunkIndex: CHUNKS, citeTarget: { chunkId: 'chunk_1', seq: 1 } })
    const p = findP('Paragraph text about the system model.')
    const method = findP('Method paragraph describing training.')
    expect(p.classList.contains('cite-flash')).toBe(true)

    // 再次触发（chunk_2，seq 递增）：上一轮 class 已清理，新命中块高亮
    await renderPanel({ chunkIndex: CHUNKS, citeTarget: { chunkId: 'chunk_2', seq: 2 } })
    expect(p.classList.contains('cite-flash')).toBe(false)
    expect(method.classList.contains('cite-flash')).toBe(true)
    expect(container.querySelectorAll('.cite-flash')).toHaveLength(1)

    act(() => {
      vi.advanceTimersByTime(3000)
    })
    expect(method.classList.contains('cite-flash')).toBe(false)
  })

  it('chunk 在索引中查不到 → message 提示且不滚动不高亮', async () => {
    await renderPanel({ chunkIndex: CHUNKS, citeTarget: { chunkId: 'chunk_999', seq: 1 } })
    expect(message.info).toHaveBeenCalledWith(NO_HIT_MSG)
    expect(vi.mocked(Element.prototype.scrollIntoView)).not.toHaveBeenCalled()
    expect(container.querySelector('.cite-flash')).toBeNull()
  })

  it('全部 snippet 未命中 → message 提示且不滚动不高亮', async () => {
    const miss: ChunkIndexEntry[] = [
      { id: 'chunk_x', page: 9, section: 'Other', snippets: ['totally absent snippet'] },
    ]
    await renderPanel({ chunkIndex: miss, citeTarget: { chunkId: 'chunk_x', seq: 1 } })
    expect(message.info).toHaveBeenCalledWith(NO_HIT_MSG)
    expect(vi.mocked(Element.prototype.scrollIntoView)).not.toHaveBeenCalled()
    expect(container.querySelector('.cite-flash')).toBeNull()
  })

  it('公式密集段回归：snippet 含 LaTeX d_{k} + DOM 同段为 KaTeX 渲染（annotation）→ 命中且不弹 toast', async () => {
    await renderPanel({ chunkIndex: CHUNKS, citeTarget: { chunkId: 'chunk_3', seq: 1 } })
    // $d_{k}$ 经共享渲染栈产出真 KaTeX span，annotation 为原始 LaTeX 源 d_{k}
    const p = findP('for small values of')
    expect(p.querySelector('.katex annotation')?.textContent).toBe('d_{k}')
    expect(p.classList.contains('cite-flash')).toBe(true)
    expect(container.querySelectorAll('.cite-flash')).toHaveLength(1)
    expect(message.info).not.toHaveBeenCalled()
    expect(vi.mocked(Element.prototype.scrollIntoView)).toHaveBeenCalledTimes(1)
  })

  it('chunkIndex 为 null 时 citeTarget 触发也安全（null props 防御）', async () => {
    await renderPanel({ chunkIndex: null, citeTarget: { chunkId: 'chunk_1', seq: 1 } })
    expect(message.info).toHaveBeenCalledWith(NO_HIT_MSG)
    expect(vi.mocked(Element.prototype.scrollIntoView)).not.toHaveBeenCalled()
    expect(container.querySelector('.cite-flash')).toBeNull()
  })
})
