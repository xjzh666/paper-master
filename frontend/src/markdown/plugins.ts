import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import rehypeRaw from 'rehype-raw'
import rehypeSlug from 'rehype-slug'
import rehypeMathInHtml from './rehypeMathInHtml'

export const remarkPlugins = [remarkGfm, remarkMath]
export const rehypePlugins = [rehypeSlug, rehypeKatex, rehypeRaw, rehypeMathInHtml]
