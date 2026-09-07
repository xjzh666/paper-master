import { describe, it, expect } from 'vitest'
import { renderToString } from 'react-dom/server'
import ReactMarkdown from 'react-markdown'
import { remarkPlugins, rehypePlugins } from './plugins'

function render(md: string): string {
  return renderToString(
    <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins}>
      {md}
    </ReactMarkdown>,
  )
}

describe('shared markdown plugin config', () => {
  it('renders inline math via KaTeX', () => {
    const out = render('$a^2+b^2=c^2$')
    expect(out).toContain('katex')
    expect(out).not.toContain('$a^2+b^2=c^2$')
  })

  it('renders display math via KaTeX', () => {
    const out = render('$$\nE = mc^2\n$$')
    expect(out).toContain('katex-display')
  })

  it('renders GFM tables', () => {
    const out = render('| a | b |\n| - | - |\n| 1 | 2 |')
    expect(out).toContain('<table>')
  })

  it('renders math inside raw HTML tables', () => {
    const out = render('<table><tr><td>$a = b$</td></tr></table>')
    expect(out).toContain('katex')
    expect(out).not.toContain('$a = b$')
  })

  it('keeps raw HTML like sub/sup', () => {
    const out = render('x<sub>1</sub> and y<sup>2</sup>')
    expect(out).toContain('<sub>')
    expect(out).toContain('<sup>')
  })
})
