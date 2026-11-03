import { describe, expect, it } from 'vitest'

import { applyBootstrapEvent, EMPTY_BOOTSTRAP_STATE } from '../../shared/src/desktop-bootstrap'

describe('shared bootstrap transitions', () => {
  it('retains upgrade intent, running time and logs across manifest discovery', () => {
    let state = applyBootstrapEvent(
      EMPTY_BOOTSTRAP_STATE,
      {
        type: 'manifest',
        stages: [],
        protocolVersion: null,
        operation: 'upgrade',
        revision: 1
      },
      100
    )

    state = applyBootstrapEvent(
      state,
      {
        type: 'manifest',
        stages: [{ name: 'products' }],
        protocolVersion: 1,
        revision: 2
      },
      200
    )
    state = applyBootstrapEvent(state, { type: 'stage', name: 'products', state: 'running', revision: 3 }, 300)
    state = applyBootstrapEvent(state, { type: 'stage', name: 'products', state: 'running', revision: 4 }, 400)
    expect(state.operation).toBe('upgrade')
    expect(state.startedAt).toBe(100)
    expect(state.stages.products.startedAt).toBe(300)

    for (let i = 5; i < 510; i++) {
      state = applyBootstrapEvent(state, { type: 'log', line: String(i), revision: i }, i)
    }

    expect(state.log).toHaveLength(500)
    expect(state.log.at(-1)?.line).toBe('509')
  })

  it('ignores already reflected events and clears old errors when dismissed', () => {
    const failure = applyBootstrapEvent(EMPTY_BOOTSTRAP_STATE, { type: 'failed', error: 'broken', revision: 8 })
    expect(applyBootstrapEvent(failure, { type: 'complete', marker: {}, revision: 7 })).toBe(failure)
    const closed = applyBootstrapEvent(failure, { type: 'dismissed', revision: 9 })
    expect(closed.error).toBeNull()
    expect(closed.active).toBe(false)
    expect(applyBootstrapEvent(closed, { type: 'failed', error: 'broken', revision: 8 })).toBe(closed)
  })
})
