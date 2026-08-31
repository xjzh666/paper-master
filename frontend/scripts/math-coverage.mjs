// Math coverage validator (Section 3 of the math-rendering pipeline).
//
// Counts how much math survives each stage of the frontend render:
//
//   Raw math candidates  (regex `$...$` / `$$...$$` on the markdown)
//   -> remark-math nodes (what remark-math parses from the markdown AST)
//   -> raw-HTML math     (math inside <table>/<caption> that remark-math misses)
//   -> KaTeX rendered    (how many of the above render without error)
//
// "Lost candidates" = raw - remark-math - raw-HTML: candidates that neither the
// markdown parser nor the raw-HTML pass picked up (OCR-broken / unclosed math).
//
// Usage (run from frontend/):
//   node scripts/math-coverage.mjs path/to/paper.md [more.md ...]
//
// The input should be the *cleaned* markdown (see `paper_reader.math_quality
// --fix`, or what `GET /api/papers/{id}/content` serves).

import { unified } from 'unified'
import remarkParse from 'remark-parse'
import remarkMath from 'remark-math'
import remarkGfm from 'remark-gfm'
import remarkRehype from 'remark-rehype'
import rehypeKatex from 'rehype-katex'
import rehypeRaw from 'rehype-raw'
import { visit } from 'unist-util-visit'
import katex from 'katex'
import fs from 'fs'

// Keep in sync with paper_reader/latex_fix.py::_MATH_SPLIT and
// src/markdown/rehypeMathInHtml.ts.
const MATH_RE = /(\$\$[\s\S]*?\$\$|\$[^$\n]*?\$)/g

function countRaw(md) {
  return (md.match(MATH_RE) || []).length
}

function renderTeX(tex, displayMode) {
  try {
    katex.renderToString(tex, { throwOnError: true, displayMode })
    return { ok: true }
  } catch (e) {
    return { ok: false, err: String(e.message || e).slice(0, 120) }
  }
}

function analyze(md) {
  const raw = countRaw(md)

  // remark-math nodes (markdown-level math).
  const remarkTree = unified().use(remarkParse).use(remarkGfm).use(remarkMath).parse(md)
  const remarkNodes = []
  visit(remarkTree, (n) => {
    if (n.type === 'math' || n.type === 'inlineMath') remarkNodes.push(n)
  })

  // Raw-HTML math: what rehype-raw turns into text nodes containing `$`.
  const htmlTree = unified()
    .use(remarkParse).use(remarkGfm).use(remarkMath)
    .use(remarkRehype, { allowDangerousHtml: true })
    .use(rehypeKatex).use(rehypeRaw)
    .runSync(unified().use(remarkParse).use(remarkGfm).use(remarkMath).parse(md))

  const htmlMath = []
  visit(htmlTree, (n) => {
    if (n.type === 'text' && typeof n.value === 'string' && n.value.includes('$')) {
      MATH_RE.lastIndex = 0
      let m
      while ((m = MATH_RE.exec(n.value)) !== null) {
        const tok = m[0]
        const display = tok.startsWith('$$')
        htmlMath.push({ display, tex: display ? tok.slice(2, -2) : tok.slice(1, -1) })
      }
    }
  })

  // Render counts.
  const remarkOk = remarkNodes.filter((n) => renderTeX(n.value, n.type === 'math').ok).length
  const htmlOk = htmlMath.filter((m) => renderTeX(m.tex, m.display).ok).length
  const remarkErr = remarkNodes.length - remarkOk
  const htmlErr = htmlMath.length - htmlOk

  const rendered = remarkOk + htmlOk
  const lost = raw - remarkNodes.length - htmlMath.length

  return { raw, remarkNodes: remarkNodes.length, remarkOk, remarkErr,
           htmlMath: htmlMath.length, htmlOk, htmlErr, rendered, lost }
}

function main(argv) {
  const files = argv
  if (!files.length) {
    console.error('usage: node scripts/math-coverage.mjs <paper.md> [...]')
    process.exit(2)
  }
  let grand = { raw: 0, remarkNodes: 0, remarkOk: 0, remarkErr: 0,
                htmlMath: 0, htmlOk: 0, htmlErr: 0, rendered: 0, lost: 0 }
  for (const f of files) {
    const md = fs.readFileSync(f, 'utf8')
    const r = analyze(md)
    console.log(`\n${f}`)
    console.log(`  Raw math candidates: ${r.raw}`)
    console.log(`  remark-math nodes:   ${r.remarkNodes}  (rendered ${r.remarkOk}, errors ${r.remarkErr})`)
    console.log(`  raw-HTML math:       ${r.htmlMath}  (rendered ${r.htmlOk}, errors ${r.htmlErr})`)
    console.log(`  KaTeX rendered:      ${r.rendered}`)
    console.log(`  Lost candidates:     ${r.lost}`)
    for (const k of Object.keys(grand)) grand[k] += r[k]
  }
  if (files.length > 1) {
    console.log(`\nTOTAL across ${files.length} files`)
    console.log(`  Raw math candidates: ${grand.raw}`)
    console.log(`  remark-math nodes:   ${grand.remarkNodes}`)
    console.log(`  raw-HTML math:       ${grand.htmlMath}`)
    console.log(`  KaTeX rendered:      ${grand.rendered}`)
    console.log(`  Lost candidates:     ${grand.lost}`)
  }
}

main(process.argv.slice(2))
