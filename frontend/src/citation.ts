/**
 * 引用定位纯函数：把 chunk snippets 在已渲染的 markdown DOM 中定位到原文块。
 *
 * 归一化规则（snippet 与 DOM textContent 两侧同规则）：
 * lowercase + 移除所有空白 + 移除 ASCII 标点 `.,;:!?(){}[]<>"'`~@#$%^*+=|\/-_`（逐字符，含连字符与下划线）。
 * DOM 侧取元素 textContent 时排除 `.katex` 子树（公式渲染产物不参与匹配）。
 */

/** lowercase + 移除所有空白 + 移除标点集（逐字符；`-` 转义避免被解析为字符范围） */
const STRIP_RE = /[\s.,;:!?()[\]{}<>"'`~@#$%^*+=|\\\/_-]/g

export function normalizeKey(s: string): string {
  return s.toLowerCase().replace(STRIP_RE, '')
}

/** 取元素 textContent（排除 .katex 子树）并归一化 */
export function elementKeyText(el: Element): string {
  const clone = el.cloneNode(true) as Element
  clone.querySelectorAll('.katex').forEach((k) => k.remove())
  return normalizeKey(clone.textContent ?? '')
}

/** DOM 候选元素：p, li, h1-h6, blockquote, td, th, pre */
const CANDIDATE_SELECTOR = 'p, li, h1, h2, h3, h4, h5, h6, blockquote, td, th, pre'

/** 元素相对 root 的深度（不在 root 下返回 -1） */
function depthUnder(root: ParentNode, el: Node): number {
  let depth = 0
  let cur: Node | null = el
  while (cur && cur !== root) {
    depth += 1
    cur = cur.parentNode
  }
  return cur === root ? depth : -1
}

/**
 * 在 root 内按 snippets 定位命中元素：
 * - 每个 snippet 独立做「候选元素 key 包含 snippet 的 normalizeKey」子串匹配
 * - 多处命中取最深元素（同深度取文档序第一个）
 * - 未命中（含归一化为空）的 snippet 跳过，不中断后续
 * - 返回按 snippet 顺序的命中元素数组
 */
export function locateCiteTargets(root: ParentNode, snippets: string[]): Element[] {
  const candidates = Array.from(root.querySelectorAll(CANDIDATE_SELECTOR))
  const results: Element[] = []
  for (const snippet of snippets) {
    const needle = normalizeKey(snippet)
    if (!needle) continue
    let best: Element | null = null
    let bestDepth = -1
    for (const el of candidates) {
      if (!elementKeyText(el).includes(needle)) continue
      const depth = depthUnder(root, el)
      if (depth > bestDepth) {
        bestDepth = depth
        best = el
      }
    }
    if (best) results.push(best)
  }
  return results
}
