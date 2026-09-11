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
})
