export type SSEEvent =
  | { type: 'tool_start'; name: string; arguments: string }
  | { type: 'tool_result'; name: string; chars: number; resources: number }
  | { type: 'answer_chunk'; delta: string }
  | { type: 'clear' }
  | { type: 'done' }
  | { type: 'error'; message: string }

export function parseFrame(frame: string): SSEEvent | null {
  let eventType = 'message'
  let data = ''
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) eventType = line.slice(6).trim()
    else if (line.startsWith('data:')) data += line.slice(5).trim()
  }
  if (!data) return null
  const payload = JSON.parse(data) as Record<string, unknown>
  switch (eventType) {
    case 'tool_start':
      return { type: 'tool_start', name: String(payload.name), arguments: String(payload.arguments) }
    case 'tool_result':
      return { type: 'tool_result', name: String(payload.name), chars: Number(payload.chars), resources: Number(payload.resources) }
    case 'answer_chunk':
      return { type: 'answer_chunk', delta: String(payload.delta) }
    case 'clear':
      return { type: 'clear' }
    case 'done':
      return { type: 'done' }
    case 'error':
      return { type: 'error', message: String(payload.message) }
    default:
      return null
  }
}

export async function postChatSSE(
  paperId: string,
  question: string,
  onEvent: (ev: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`/api/papers/${paperId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
    signal,
  })
  if (!res.ok || !res.body) throw new Error(`chat failed: ${res.status}`)
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      const ev = parseFrame(frame)
      if (ev) onEvent(ev)
    }
  }
}
