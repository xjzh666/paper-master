// @vitest-environment jsdom
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react'
import PaperListSidebar from './PaperListSidebar'
import { api } from '../api/client'
import type { ArxivResult, ZoteroItem } from '../api/client'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      collections: vi.fn(async () => []),
      items: vi.fn(async () => []),
      arxivSearch: vi.fn(),
    },
  }
})

// 摘要超长 + 尾部标记：验证列表只展示截断后的摘要
const RESULT: ArxivResult = {
  arxiv_id: '1706.03762',
  title: 'Attention Is All You Need',
  authors: ['Ashish Vaswani', 'Noam Shazeer', 'Niki Parmar', 'Jakob Uszkoreit'],
  abstract: 'a'.repeat(200) + 'UNIQUE_TAIL_MARKER',
  published: '2017-06-07T17:57:34Z',
  updated: '2017-06-12T23:41:29Z',
  categories: ['cs.CL'],
  pdf_url: 'https://arxiv.org/pdf/1706.03762',
  abs_url: 'https://arxiv.org/abs/1706.03762',
}

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
})

afterEach(() => {
  act(() => {
    root.unmount()
  })
  container.remove()
  vi.clearAllMocks()
})

async function renderSidebar(onOpenArxiv?: (item: ArxivResult) => void) {
  const onOpen = vi.fn((_item: ZoteroItem) => {})
  await act(async () => {
    root.render(<PaperListSidebar onOpen={onOpen} onOpenArxiv={onOpenArxiv ?? (() => {})} />)
  })
  return onOpen
}

/** 点击激活「arXiv 搜索」页签，返回当前激活 pane（inactive pane 可能仍在 DOM，需按 active 限定） */
async function activateArxivTab(): Promise<Element> {
  const tab = [...container.querySelectorAll('.ant-tabs-tab')].find(
    (t) => t.textContent === 'arXiv 搜索',
  )
  expect(tab, 'arXiv 搜索页签存在').toBeDefined()
  act(() => {
    tab!.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
  })
  const pane = container.querySelector('.ant-tabs-tabpane-active')
  expect(pane, 'arXiv pane 激活').toBeDefined()
  return pane!
}

/** React 受控输入：走原生 value setter + input 事件，让 onChange 生效（包 act 防 state 更新逃逸） */
function setInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!
  act(() => {
    setter.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

/** 在已激活的 arXiv pane 内触发一次搜索（受控输入 + 搜索按钮点击） */
async function searchArxiv(pane: Element, q: string) {
  const input = pane.querySelector('input') as HTMLInputElement
  expect(input, '搜索输入框存在').toBeTruthy()
  setInputValue(input, q)
  const btn = pane.querySelector('.ant-input-search-button') as HTMLElement
  expect(btn, '搜索按钮存在').toBeTruthy()
  await act(async () => {
    btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
  })
}

describe('PaperListSidebar 页签结构', () => {
  it('渲染两个页签：Zotero 论文库 / arXiv 搜索', async () => {
    await renderSidebar()
    const labels = [...container.querySelectorAll('.ant-tabs-tab')].map((t) => t.textContent)
    expect(labels).toContain('Zotero 论文库')
    expect(labels).toContain('arXiv 搜索')
  })
})

describe('PaperListSidebar arXiv 搜索', () => {
  it('搜索后 List 渲染结果（标题/作者前3/年份/arxiv_id/摘要截断），点击条目以完整 ArxivResult 触发 onOpenArxiv 一次', async () => {
    vi.mocked(api.arxivSearch).mockResolvedValue({ results: [RESULT] })
    const onOpenArxiv = vi.fn()
    await renderSidebar(onOpenArxiv)

    const pane = await activateArxivTab()
    const input = pane.querySelector('input') as HTMLInputElement
    expect(input).toBeTruthy()
    setInputValue(input, 'attention')
    const btn = pane.querySelector('.ant-input-search-button') as HTMLElement
    expect(btn, '搜索按钮存在').toBeTruthy()
    await act(async () => {
      btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    })

    expect(api.arxivSearch).toHaveBeenCalledWith('attention')
    const doc = container.textContent ?? ''
    expect(doc).toContain('Attention Is All You Need')
    expect(doc).toContain('Ashish Vaswani') // 作者前 3
    expect(doc).not.toContain('Jakob Uszkoreit') // 第 4 作者不展示
    expect(doc).toContain('2017') // 年份（published 前 4 位）
    expect(doc).toContain('1706.03762') // arxiv_id Tag
    expect(doc).not.toContain('UNIQUE_TAIL_MARKER') // 摘要截断
    expect(doc).not.toContain('OpenAlex 兜底') // source 缺失视为 arxiv，无兜底标签

    const item = [...container.querySelectorAll('.ant-list-item')].find((li) =>
      li.textContent?.includes('Attention Is All You Need'),
    )
    expect(item, '结果条目存在').toBeDefined()
    act(() => {
      item!.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    })
    expect(onOpenArxiv).toHaveBeenCalledTimes(1)
    expect(onOpenArxiv).toHaveBeenCalledWith(RESULT)
  })

  it('source=="openalex" 时结果区显示「OpenAlex 兜底」Tag', async () => {
    vi.mocked(api.arxivSearch).mockResolvedValue({ results: [RESULT], source: 'openalex' })
    await renderSidebar()

    const pane = await activateArxivTab()
    const input = pane.querySelector('input') as HTMLInputElement
    setInputValue(input, 'attention')
    const btn = pane.querySelector('.ant-input-search-button') as HTMLElement
    await act(async () => {
      btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    })

    const tag = [...container.querySelectorAll('.ant-tag')].find(
      (t) => t.textContent === 'OpenAlex 兜底',
    )
    expect(tag, 'OpenAlex 兜底 Tag 存在').toBeDefined()
    expect(tag!.className, 'OpenAlex 兜底保持橙色').toContain('ant-tag-orange')
    const tagTexts = [...container.querySelectorAll('.ant-tag')].map((t) => t.textContent)
    expect(tagTexts, 'openalex 时不显示 s2 标签').not.toContain('Semantic Scholar')
  })
})

describe('PaperListSidebar 三源来源标签与引用数', () => {
  it('source=="s2" 时显示蓝色「Semantic Scholar」Tag，作者行显示「被引 192499」（数字原样）', async () => {
    const s2Result: ArxivResult = {
      ...RESULT,
      tldr: 'Sequence transduction models without recurrence.',
      citation_count: 192499,
    }
    vi.mocked(api.arxivSearch).mockResolvedValue({ results: [s2Result], source: 's2' })
    await renderSidebar()

    const pane = await activateArxivTab()
    await searchArxiv(pane, 'attention')

    const tag = [...container.querySelectorAll('.ant-tag')].find(
      (t) => t.textContent === 'Semantic Scholar',
    )
    expect(tag, 'Semantic Scholar Tag 存在').toBeDefined()
    expect(tag!.className, 'Semantic Scholar 标签为蓝色').toContain('ant-tag-blue')
    const doc = container.textContent ?? ''
    expect(doc).toContain('被引 192499')
    expect(doc, '不加千分位').not.toContain('192,499')
  })

  it('source=="arxiv" 且无 citation_count 时无任何来源 Tag，作者行不含「被引」', async () => {
    vi.mocked(api.arxivSearch).mockResolvedValue({ results: [RESULT] })
    await renderSidebar()

    const pane = await activateArxivTab()
    await searchArxiv(pane, 'attention')

    const tagTexts = [...container.querySelectorAll('.ant-tag')].map((t) => t.textContent)
    expect(tagTexts, 'arxiv 源无 Semantic Scholar 标签').not.toContain('Semantic Scholar')
    expect(tagTexts, 'arxiv 源无 OpenAlex 兜底标签').not.toContain('OpenAlex 兜底')
    expect(container.textContent ?? '').not.toContain('被引')
  })

  it('citation_count==null（S2 未返回引用数）时干净降级：来源 Tag 照常，作者行不显示「被引」', async () => {
    const noCitation: ArxivResult = { ...RESULT, citation_count: null }
    vi.mocked(api.arxivSearch).mockResolvedValue({ results: [noCitation], source: 's2' })
    await renderSidebar()

    const pane = await activateArxivTab()
    await searchArxiv(pane, 'attention')

    const tag = [...container.querySelectorAll('.ant-tag')].find(
      (t) => t.textContent === 'Semantic Scholar',
    )
    expect(tag, '来源标识不受 citation_count 缺失影响').toBeDefined()
    expect(container.textContent ?? '').not.toContain('被引')
  })
})
