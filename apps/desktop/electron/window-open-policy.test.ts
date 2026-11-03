import { describe, expect, it } from 'vitest'
import { createWindowOpenHandler, describeDeniedUrl } from './window-open-policy'

describe('window open policy', () => {
  it.each(['https://hermes-agent.nousresearch.com/docs/skills', 'https://example.com', 'file:///private', 'javascript:alert(1)', 'mailto:test@example.com'])(
    'denies unsolicited windows for %s', url => {
      expect(createWindowOpenHandler()({ url })).toEqual({ action: 'deny' })
    }
  )
  it('still denies if logging fails', () => {
    const handler = createWindowOpenHandler(() => { throw new Error('log unavailable') })
    expect(handler({ url: 'https://example.com' })).toEqual({ action: 'deny' })
  })
  it('logs only origins, never tokens or private paths', () => {
    expect(describeDeniedUrl('https://example.com/path?token=secret')).toBe('https://example.com')
    expect(describeDeniedUrl('data:text/html,foo')).toBe('data:')
    expect(describeDeniedUrl('not a url')).toBe('<unparseable>')
  })
})
