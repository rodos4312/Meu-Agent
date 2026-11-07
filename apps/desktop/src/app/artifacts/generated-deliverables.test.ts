import { expect, it } from 'vitest'

import type { SessionInfo } from '@/types/hermes'

import { collectArtifactsForSession, loadArtifactsForSessions } from './artifact-utils'
import { generatedDeliverables, MAX_INDEX_INLINE_CHARS } from './generated-deliverables'

const html = (body: string) => `<!doctype html><html><head><title>Report</title></head><body>${body}</body></html>`
const fence = (body: string) => '```html\n' + body + '\n```'
const session = { id: 'one', title: 'Project', profile: 'writer' } as SessionInfo

it('indexes completed documents, preserves content, and leaves snippets and incomplete fences alone', () => {
  const document = html('Παραδοτέο '.repeat(30))
  expect(generatedDeliverables(fence(document))[0]).toMatchObject({ kind: 'html', title: 'Report', content: document })
  expect(generatedDeliverables('```html\n' + document)).toEqual([])
  expect(generatedDeliverables('```js\nconsole.log(1)\n```')).toEqual([])
  expect(generatedDeliverables('~~~~html\n' + document + '\n~~~~')).toHaveLength(1)
})

it('keeps user examples out and deduplicates repeated assistant deliveries within their session', () => {
  const content = fence(html('Document '.repeat(30)))

  const records = collectArtifactsForSession(session, [
    { role: 'user', content: fence(html('Example '.repeat(30))) },
    { role: 'assistant', content },
    { role: 'assistant', content }
  ])

  expect(records.filter(item => item.inline)).toHaveLength(1)
  expect(records.find(item => item.inline)).toMatchObject({
    sessionId: 'one',
    profile: 'writer',
    sessionTitle: 'Project'
  })
})

it('retains all delivered entries and disk paths when the bounded inline cache fills', async () => {
  const documents = Array.from({ length: 6 }, (_, index) => ({
    role: 'assistant' as const,
    content: fence(html(String(index).repeat(450_000))) + '\nMEDIA:/output/report-' + index + '.txt'
  }))

  const { artifacts, failures } = await loadArtifactsForSessions([session], async () => ({ messages: documents }))
  expect(failures).toEqual([])
  expect(artifacts.filter(item => item.inline)).toHaveLength(6)
  expect(artifacts.filter(item => !item.inline && item.kind === 'file')).toHaveLength(6)
  expect(artifacts.some(item => item.inline && item.inline.content === undefined)).toBe(true)
  expect(artifacts.reduce((sum, item) => sum + (item.inline?.content?.length || 0), 0)).toBeLessThanOrEqual(
    MAX_INDEX_INLINE_CHARS
  )
})
