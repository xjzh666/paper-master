# Spec: 对话面板 markdown + 公式渲染

日期: 2026-09-01（实现后补写存档）
状态: 已实现

## 背景

ChatPanel 的助手消息此前用 `Typography.Paragraph` 纯文本渲染，LLM 输出的 markdown（列表、代码块、表格、LaTeX 公式）全部以原始语法显示。阅读区（ReadingPanel）已有完整的渲染栈（react-markdown + remark-math/rehype-katex + rehype-raw + rehypeMathInHtml），但插件配置内联在 ReadingPanel 里，无法复用。

## 目标

- 助手消息按 markdown 渲染，公式、表格、代码块、列表与阅读区表现一致
- 流式输出下渲染正确，历史消息不因新 chunk 重复解析
- 用户消息保持纯文本（pre-wrap）

## 非目标

- 不做"未闭合 `$$`/代码块尾部缓冲"——中间态闪烁按普通文本显示、闭合后成型，先观察实际体验再决定是否优化
- 不做 HTML sanitize——本地单用户应用，内容来自用户自己的 LLM，与阅读区策略一致

## 方案

- 新增 `frontend/src/markdown/plugins.ts`：导出共享 `remarkPlugins`（gfm + math）与 `rehypePlugins`（slug + katex + raw + MathInHtml），阅读区与对话区共用同一配置
- ChatPanel 新增 `MarkdownMessage`（`React.memo` 包裹的 react-markdown 组件，`markdown-body` 样式 + 14px 字号）
- 流式策略沿用"增量 buffer + 全量重渲染最后一条"：`answer_chunk` 只更新最后一条消息内容，memo 保证历史消息跳过重解析；单条回答几 KB，全量重解析开销可忽略
- 渲染时机问题（为什么流式不影响正确性）：react-markdown 是声明式渲染，未闭合分隔符不构成 math 节点，按普通文本显示

## 涉及文件

- `frontend/src/markdown/plugins.ts`（新增）
- `frontend/src/markdown/plugins.test.tsx`（新增）
- `frontend/src/components/ChatPanel.tsx`（助手消息分支改为 MarkdownMessage）
- `frontend/src/components/ReadingPanel.tsx`（改用共享插件配置）

## 测试计划

- `plugins.test.tsx` 5 例：inline/display 公式 KaTeX 渲染、GFM 表格、原生 HTML 表内公式、sub/sup 保留
- 全量 vitest（17 例）+ `npm run build` 通过

## 验收标准

- 对话区助手消息的公式/表格/代码块渲染与阅读区一致
- 流式回答过程中历史消息不重渲染
- 未闭合 `$$` 在中间态按普通文本显示，闭合后自动成型
