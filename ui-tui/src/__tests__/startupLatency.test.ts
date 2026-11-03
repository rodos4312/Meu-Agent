import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createGatewayEventHandler } from '../app/createGatewayEventHandler.js'
import { resetOverlayState } from '../app/overlayStore.js'
import { resetTurnState } from '../app/turnStore.js'
import { resetUiState } from '../app/uiStore.js'

const ref = <T>(current: T) => ({ current })

const buildCtx = (request: ReturnType<typeof vi.fn>) =>
  ({
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
  }) as any

const latencyCalls = (request: ReturnType<typeof vi.fn>) =>
  request.mock.calls.filter(([method]) => method === 'shared_metrics.startup_latency')

describe('Meu startup privacy', () => {
  beforeEach(() => {
    resetOverlayState()
    resetUiState()
    resetTurnState()
  })

  it('does not report launch metrics across repeated gateway.ready and handler remounts', () => {
    // No telemetry call is allowed, including against older gateways.
    const request = vi.fn(async () => {
      throw new Error('method not found')
    })

    const ready = { payload: {}, type: 'gateway.ready' } as any
    const onEvent = createGatewayEventHandler(buildCtx(request))

    onEvent(ready)
    onEvent(ready)
    // Reconnecting and remounting must not start reporting.
    createGatewayEventHandler(buildCtx(request))(ready)

    const calls = latencyCalls(request)

    expect(calls).toEqual([])
  })
})
