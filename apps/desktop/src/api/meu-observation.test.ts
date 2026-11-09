import { expect, it } from 'vitest'

import { decodeMeuObservation } from './meu-observation'

it('accepts only bounded visible text for the exact displayed conversation', () => {
  const view = { id: 'own', busy: true, draft: 'Live', messages: [{ role: 'user', content: 'Question', message_uid: 'a'.repeat(32) }] }
  expect(decodeMeuObservation(view, 'own')).toBe(view)
  expect(decodeMeuObservation(null, 'own')).toBeNull()

  for (const bad of [
    { ...view, id: 'another' },
    { ...view, messages: {} },
    { ...view, messages: [{ ...view.messages[0], role: 'tool' }] },
    { ...view, messages: [view.messages[0], view.messages[0]] },
    { ...view, draft: 'x'.repeat(256 * 1024 + 1) }
  ]) {
    expect(() => decodeMeuObservation(bad, 'own')).toThrow()
  }
})
