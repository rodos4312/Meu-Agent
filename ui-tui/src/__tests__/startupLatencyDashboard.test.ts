import { describe, expect, it, vi } from 'vitest'

import { createGatewayEventHandler } from '../app/createGatewayEventHandler.js'
import type * as EnvModule from '../config/env.js'

// Dashboard mode is resolved at module load; exercise its ready handler independently.
vi.mock('../config/env.js', async importActual => ({
  ...(await importActual<typeof EnvModule>()),
  DASHBOARD_TUI_MODE: true
}))

const ref = <T>(current: T) => ({ current })

describe('startup latency in a dashboard-embedded TUI', () => {
  it('does not report launch metrics when a dashboard chat tab opens', () => {
    const request = vi.fn(async () => ({ ok: true }))

    const ctx = {
      composer: { dequeue: () => undefined, queueEditRef: ref(null), sendQueued: vi.fn(), setInput: vi.fn() },
      gateway: { gw: { request }, rpc: vi.fn(async () => null) },
      session: {
        STARTUP_RESUME_ID: '',
        colsRef: ref(80),
        newSession: vi.fn(),
        resetSession: vi.fn(),
        resumeById: vi.fn(),
        setCatalog: vi.fn()
      },
      submission: { submitRef: { current: vi.fn() } },
      system: { bellOnComplete: false, sys: vi.fn() },
      transcript: { appendMessage: vi.fn(), panel: vi.fn(), setHistoryItems: vi.fn() },
      voice: { setProcessing: vi.fn(), setRecording: vi.fn(), setVoiceEnabled: vi.fn() }
    } as any

    createGatewayEventHandler(ctx)({ payload: {}, type: 'gateway.ready' } as any)

    expect(request.mock.calls.filter(([method]) => method === 'shared_metrics.startup_latency')).toEqual([])
  })
})
