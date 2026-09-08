// @vitest-environment jsdom
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react'
import ChatPanel from './ChatPanel'

const CITE_MD = '见 [§3.2 p.4](cite:chunk_12) 的讨论，另见 [论文主页](https://example.com)。'

interface Msg {
  role: 'user' | 'assistant'
  content: string
}

function mockFetch(messages: Msg[]) {
  return vi.fn(async () => ({ ok: true, json: async () => ({ messages }) }))
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
  vi.unstubAllGlobals()
})

async function renderPanel(onCite?: (chunkId: string) => void) {
  await act(async () => {
    root.render(<ChatPanel paperId="paper1" disabled={false} onCite={onCite} />)
  })
}

function click(el: Element): MouseEvent {
  const evt = new MouseEvent('click', { bubbles: true, cancelable: true })
  el.dispatchEvent(evt)
  return evt
}

describe('ChatPanel cite links', () => {
  it('renders <a href="cite:chunk_12"> for [§3.2 p.4](cite:chunk_12) (urlTransform 放行)', async () => {
    vi.stubGlobal('fetch', mockFetch([{ role: 'assistant', content: CITE_MD }]))
    await renderPanel()
    const a = container.querySelector('a[href="cite:chunk_12"]')
    expect(a).not.toBeNull()
    expect(a?.textContent).toContain('§3.2 p.4')
  })

  it('clicking the cite link: preventDefault (不触发导航) 且 onCite 收到 "chunk_12"', async () => {
    vi.stubGlobal('fetch', mockFetch([{ role: 'assistant', content: CITE_MD }]))
    const onCite = vi.fn()
    await renderPanel(onCite)
    const a = container.querySelector('a[href="cite:chunk_12"]')
    expect(a).not.toBeNull()
    const evt = click(a!)
    expect(evt.defaultPrevented).toBe(true)
    expect(onCite).toHaveBeenCalledTimes(1)
    expect(onCite).toHaveBeenCalledWith('chunk_12')
  })

  it('clicking a normal https link: onCite 不被调用，默认行为不受影响', async () => {
    vi.stubGlobal('fetch', mockFetch([{ role: 'assistant', content: CITE_MD }]))
    const onCite = vi.fn()
    await renderPanel(onCite)
    const a = container.querySelector('a[href="https://example.com"]')
    expect(a).not.toBeNull()
    const evt = click(a!)
    expect(onCite).not.toHaveBeenCalled()
    expect(evt.defaultPrevented).toBe(false)
  })

  it('未传 onCite prop 时点击 cite 链接不报错', async () => {
    vi.stubGlobal('fetch', mockFetch([{ role: 'assistant', content: CITE_MD }]))
    await renderPanel()
    const a = container.querySelector('a[href="cite:chunk_12"]')
    expect(a).not.toBeNull()
    let evt: MouseEvent | undefined
    expect(() => {
      evt = click(a!)
    }).not.toThrow()
    expect(evt?.defaultPrevented).toBe(true)
  })
})
