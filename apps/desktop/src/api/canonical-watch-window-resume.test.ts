// @vitest-environment node
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { expect, test, vi } from 'vitest'

import { primaryResumeParams, resumeWatchWithHistory } from '@/app/session/hooks/use-session-actions/resume-owner'
import type { SessionMessagesResponse, SessionResumeResult } from '@/types/hermes'

import { CanonicalDesktopProtocol } from './canonical-protocol'

// Watch and regular resume requests must fit the generated canonical contract.
const doc = JSON.parse(
  readFileSync(join(process.cwd(), '..', 'shared', 'src', 'gateway-contract.openrpc.json'), 'utf8')
)

const resumeRef = doc['x-canonical-methods'].find((m: { name: string }) => m.name === 'session.resume').params[0].schema
  .$ref

const RESUME_KEYS = new Set(Object.keys(doc.components.schemas[resumeRef.split('/').at(-1)].properties))

test.each([
  ['legacy watch snapshot', true, undefined, false],
  ['watch with paged history', true, undefined, true],
  ['cold resume', false, undefined, false],
  ['authoritative snapshot', false, true, false]
] as const)('%s: the canonical resume frame fits the owner contract', (_label, watchWindow, snapshot, paged) => {
  const frame = new CanonicalDesktopProtocol().prepare(
    'session.resume',
    primaryResumeParams('s', watchWindow, snapshot, 'work', paged)
  )

  expect(Object.keys(frame).filter(key => !RESUME_KEYS.has(key))).toEqual([])
  expect(frame).toMatchObject({ session_id: 's', profile: 'work' })

  if (watchWindow) {
    expect(frame).toMatchObject({ omit_messages: paged, defer_history: false })
  }
})

const attached = {
  message_count: 121,
  messages: [],
  messages_omitted: true,
  resumed: 'child',
  session_id: 'watch'
} as SessionResumeResult

test('a watch subscribes before reading the latest stored page', async () => {
  const page = {
    messages: [{ content: 'Child finished during attach', role: 'assistant' }],
    session_id: 'child'
  } as SessionMessagesResponse

  const resume = vi.fn<(paged: boolean) => Promise<SessionResumeResult>>().mockResolvedValue(attached)
  const readPage = vi.fn<() => Promise<SessionMessagesResponse>>().mockResolvedValue(page)

  await expect(resumeWatchWithHistory(resume, readPage)).resolves.toEqual({ page, resumed: attached })
  expect(resume.mock.calls).toEqual([[true]])
  expect(resume.mock.invocationCallOrder[0]).toBeLessThan(readPage.mock.invocationCallOrder[0]!)
})

test('a watch can still open when the owner has no REST history route', async () => {
  const full = { ...attached, messages: [{ content: 'Stored answer', role: 'assistant' }], messages_omitted: false }

  const resume = vi
    .fn<(paged: boolean) => Promise<SessionResumeResult>>()
    .mockResolvedValueOnce(attached)
    .mockResolvedValueOnce(full as SessionResumeResult)

  const readPage = vi.fn<() => Promise<SessionMessagesResponse>>().mockRejectedValue(new Error('No history endpoint'))

  await expect(resumeWatchWithHistory(resume, readPage)).resolves.toEqual({ page: null, resumed: full })
  expect(resume.mock.calls).toEqual([[true], [false]])
})
