// Render `$...$` / `$$...$$` that live *inside raw HTML* (e.g. `<table>` cell
// content) which remark-math cannot see. remark-math only processes the
// markdown AST, and `rehype-raw` expands raw HTML *after* rehype-katex has
// already run, so table-cell math is left as literal dollar text.
//
// This plugin runs *after* rehype-raw and renders any remaining math in text
// nodes (table cells, captions inside raw HTML) via KaTeX.
//
// Keep the delimiter regex in sync with `paper_reader/latex_fix.py::_MATH_SPLIT`
// and `frontend/scripts/math-coverage.mjs`.

import { fromHtmlIsomorphic } from 'hast-util-from-html-isomorphic'
import { SKIP, visitParents } from 'unist-util-visit-parents'
import katex from 'katex'
import type { Root } from 'hast'

// Inline `$...$` (single line) and display `$$...$$` (may span lines).
const MATH_RE = /(\$\$[\s\S]*?\$\$|\$[^$\n]*?\$)/g

export default function rehypeMathInHtml() {
  return function (tree: Root) {
    visitParents(tree, 'text', (node, ancestors) => {
      const value = node.value
      if (typeof value !== 'string' || !value.includes('$')) return

      const parent = ancestors[ancestors.length - 1]
      if (!parent || !Array.isArray(parent.children)) return
      const index = parent.children.indexOf(node)
      if (index < 0) return

      // Only process nodes that contain at least one well-formed math pair.
      const matches: RegExpExecArray[] = []
      MATH_RE.lastIndex = 0
      let m: RegExpExecArray | null
      while ((m = MATH_RE.exec(value)) !== null) matches.push(m)
      if (matches.length === 0) return

      const parts: Array<Record<string, unknown>> = []
      let last = 0
      for (const match of matches) {
        if (match.index > last) {
          parts.push({ type: 'text', value: value.slice(last, match.index) })
        }
        const tok = match[0]
        const display = tok.startsWith('$$')
        const tex = display ? tok.slice(2, -2) : tok.slice(1, -1)
        try {
          const html = katex.renderToString(tex, {
            displayMode: display,
            throwOnError: true,
          })
          const frag = fromHtmlIsomorphic(html, { fragment: true })
          parts.push(...(frag.children as unknown as Array<Record<string, unknown>>))
        } catch {
          // Never drop content: fall back to a red error box (same as rehype-katex).
          const html = katex.renderToString(tex, {
            displayMode: display,
            throwOnError: false,
            strict: 'ignore',
          })
          const frag = fromHtmlIsomorphic(html, { fragment: true })
          parts.push(...(frag.children as unknown as Array<Record<string, unknown>>))
        }
        last = match.index + tok.length
      }
      if (last < value.length) {
        parts.push({ type: 'text', value: value.slice(last) })
      }

      parent.children.splice(index, 1, ...(parts as never[]))
      return SKIP
    })
  }
}
