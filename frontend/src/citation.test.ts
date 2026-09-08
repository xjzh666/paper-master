// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import { normalizeKey, elementKeyText, locateCiteTargets } from './citation'

function dom(html: string): HTMLElement {
  const root = document.createElement('div')
  root.innerHTML = html
  return root
}

describe('normalizeKey', () => {
  it('oracle：大小写、空白与标点差异归一化后等价', () => {
    expect(normalizeKey('We evaluate SOTK on 200 nodes.')).toBe('weevaluatesotkon200nodes')
    expect(normalizeKey('we_evaluate,\t SOTK\n on-200 nodes.')).toBe('weevaluatesotkon200nodes')
  })

  it('逐字符移除完整标点集（含连字符与下划线），& 不在集合内', () => {
    expect(normalizeKey(". , ; : ! ? ( ) { } [ ] < > \" ' ` ~ @ # $ % ^ * + = | \\ / - _")).toBe('')
    expect(normalizeKey('A&B 100%')).toBe('a&b100')
  })
})

describe('elementKeyText', () => {
  it('取 textContent 时排除 .katex 子树', () => {
    const p = dom('<p>Hello <span class="katex">x²junk</span> world</p>').querySelector('p')!
    expect(elementKeyText(p)).toBe('helloworld')
  })
})

describe('locateCiteTargets', () => {
  it('li 与 p 都在候选集且都命中时，取最深元素 p', () => {
    const root = dom('<ul><li><p>target text here</p></li></ul>')
    const hits = locateCiteTargets(root, ['target text'])
    expect(hits).toHaveLength(1)
    expect(hits[0].tagName).toBe('P')
  })

  it('oracle：未命中的 snippet 跳过，不中断后续 snippet 匹配', () => {
    const root = dom('<p>paragraph text here</p><ul><li>item one text</li></ul>')
    const hits = locateCiteTargets(root, ['paragraph text', 'nonexistent snippet', '- item one text'])
    expect(hits).toHaveLength(2)
    expect(hits[0].tagName).toBe('P')
    expect(hits[1].tagName).toBe('LI')
  })

  it('候选元素限定 p, li, h1-h6, blockquote, td, th, pre：div 不参与', () => {
    const root = dom('<div>paragraph text here</div>')
    expect(locateCiteTargets(root, ['paragraph text'])).toHaveLength(0)
  })

  it('候选选择器覆盖全部候选标签', () => {
    const root = dom(
      '<h1>head one</h1><h2>head two</h2><h3>head three</h3><h4>head four</h4>' +
        '<h5>head five</h5><h6>head six</h6><blockquote>quote body</blockquote>' +
        '<table><tr><td>cell body</td><th>header body</th></tr></table><pre>code body</pre><p>para body</p>',
    )
    const hits = locateCiteTargets(root, [
      'head one',
      'head two',
      'head three',
      'head four',
      'head five',
      'head six',
      'quote body',
      'cell body',
      'header body',
      'code body',
      'para body',
    ])
    expect(hits.map((h) => h.tagName)).toEqual([
      'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'BLOCKQUOTE', 'TD', 'TH', 'PRE', 'P',
    ])
  })

  it('katex 子树内容不参与匹配', () => {
    const root = dom('<p>secret formula <span class="katex">E=mc^2 uniquejunk</span></p>')
    expect(locateCiteTargets(root, ['uniquejunk'])).toHaveLength(0)
    expect(locateCiteTargets(root, ['secret formula'])).toHaveLength(1)
  })

  it('归一化为空的 snippet 视为未命中跳过', () => {
    const root = dom('<p>paragraph text</p>')
    const hits = locateCiteTargets(root, ['', '   ', 'paragraph text'])
    expect(hits).toHaveLength(1)
  })

  it('匹配是归一化子串匹配：标点/大小写差异不影响命中', () => {
    const root = dom('<p>The QUICK brown-fox!</p>')
    expect(locateCiteTargets(root, ['quick brown, fox'])).toHaveLength(1)
  })
})
