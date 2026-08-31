import { describe, it, expect } from 'vitest'
import { unified } from 'unified'
import remarkParse from 'remark-parse'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import remarkRehype from 'remark-rehype'
import rehypeKatex from 'rehype-katex'
import rehypeRaw from 'rehype-raw'
import rehypeMathInHtml from './rehypeMathInHtml'

function render(md: string): string {
  const proc = unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(remarkMath)
    .use(remarkRehype, { allowDangerousHtml: true })
    .use(rehypeKatex)
    .use(rehypeRaw)
    .use(rehypeMathInHtml)
  const tree = proc.runSync(proc.parse(md))
  return JSON.stringify(tree)
}

describe('rehypeMathInHtml', () => {
  it('renders $..$ inside an HTML table cell via KaTeX', () => {
    const out = render('<table><tr><td>$a = b$</td></tr></table>')
    expect(out).not.toContain('$a = b$')
    expect(out).toContain('katex')
  })

  it('renders display $$..$$ inside a table cell', () => {
    const out = render('<table><tr><td>$$x^{2}$$</td></tr></table>')
    expect(out).not.toContain('$$x^{2}$$')
    expect(out).toContain('katex')
  })

  it('keeps prose around the math intact', () => {
    const out = render('<table><tr><td>The set of $k$ tenants</td></tr></table>')
    expect(out).toContain('The set of')
    expect(out).toContain('tenants')
    expect(out).not.toContain('$k$')
    expect(out).toContain('katex')
  })

  it('leaves currency amounts (no closing $) untouched', () => {
    const out = render('<table><tr><td>cost $500 total</td></tr></table>')
    expect(out).toContain('$500')
    expect(out).not.toContain('katex')
  })
})
