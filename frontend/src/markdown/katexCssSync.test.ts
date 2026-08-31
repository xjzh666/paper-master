import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { describe, expect, it } from 'vitest'
import katex from 'katex'

// Regression guard for the formula-overlap bug (2026-08): main.tsx imports the
// CSS from the top-level katex, while rehype-katex renders with its own katex
// dependency. When the two diverged (CSS 0.18 vs renderer 0.16), KaTeX's
// layout rules no longer matched the emitted class names:
// `.katex .strut { display: inline-block }` went missing, so struts stopped
// reserving line-box height and tall inline math (multi-row arrays like the
// "parameter matrices" formula) overlapped the adjacent text lines.
const require = createRequire(import.meta.url)

const cssPath = require.resolve('katex/dist/katex.min.css')
const css = readFileSync(cssPath, 'utf8')

const versionOf = (req: NodeRequire) =>
  (JSON.parse(readFileSync(req.resolve('katex/package.json'), 'utf8')) as { version: string }).version

describe('katex CSS / renderer sync', () => {
  it('renders with the same katex version main.tsx loads CSS from', () => {
    const topLevel = versionOf(require)
    const viaRehypeKatex = versionOf(createRequire(require.resolve('rehype-katex')))
    expect(topLevel).toBe(viaRehypeKatex)
  })

  it('CSS covers the strut class emitted for tall inline math', () => {
    const html = katex.renderToString('\\begin{array}{c} a \\\\ b \\end{array}', {
      displayMode: false,
      output: 'html',
    })
    const m = html.match(/class="((?:katex-)?strut)"/)
    expect(m, 'strut span missing from inline array HTML').toBeTruthy()
    // Selector may appear merged, e.g. `.katex .base,.katex .strut{display:inline-block}`.
    expect(css).toContain('strut{display:inline-block}')
    expect(css).toContain(`.katex .${m![1]}`)
  })

  it('strut height covers a multi-row inline array (no line overlap)', () => {
    const html = katex.renderToString('\\begin{array}{c} a \\\\ b \\end{array}', {
      displayMode: false,
      output: 'html',
    })
    const m = html.match(/class="(?:katex-)?strut" style="height:([0-9.]+)em/)
    expect(m, 'strut height missing').toBeTruthy()
    // A 2-row array needs ~2.4em; plain text lines are ~1.2em. If the strut
    // collapses (rule missing), inline arrays overlap the adjacent lines.
    expect(Number(m![1])).toBeGreaterThan(2)
  })

  it('CSS covers the sizing classes used for script-size sub/superscripts', () => {
    const html = katex.renderToString('x^{2}_{i}', { displayMode: false, output: 'html' })
    const m = html.match(/class="((?:katex-)?sizing) reset-size6 size3 mtight"/)
    expect(m, 'sizing span missing from sub/superscript HTML').toBeTruthy()
    expect(css).toContain(`.katex .${m![1]}.reset-size6.size3{font-size:`)
  })
})
