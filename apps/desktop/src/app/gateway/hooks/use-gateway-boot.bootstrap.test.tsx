import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import type { DesktopBootstrapEvent } from '@/global'
import { BACKEND_BOOT_WAIT_TIMEOUT_MS } from '@/lib/with-timeout'
import { $desktopBoot } from '@/store/boot'
import { $gatewayState } from '@/store/session'

import { deferred } from '../../../test/deferred'
import { FakeWebSocket } from '../../../test/fake-gateway-socket'
import { takeGatewaySurvivor } from './gateway-hmr-survivor'
import { useGatewayBoot } from './use-gateway-boot'

vi.mock(import('@/store/notifications'), async original => ({ ...(await original()), notifyError: vi.fn() }))
vi.mock(import('@/store/terminal-backend-warning'), () => ({
  warnIfTerminalBackendUnavailable: vi.fn(async () => false)
}))

const originalWebSocket = globalThis.WebSocket
const connection = {
  mode: 'local' as const,
  connectionId: 'local',
  profile: 'default',
  baseUrl: 'http://127.0.0.1:9191',
  wsUrl: 'ws://127.0.0.1:9191/api/ws',
  authMode: 'token' as const
}

function Harness() {
  useGatewayBoot({
    beforeConnectionSwitch: () => undefined,
    handleGatewayEvent: () => undefined,
    handleServerRequest: () => false,
    onConnectionReady: () => undefined,
    onGatewayReady: () => undefined,
    refreshHermesConfig: async () => undefined,
    refreshSessions: async () => undefined
  })
  return null
}

beforeEach(() => {
  vi.useFakeTimers()
  FakeWebSocket.mode = 'open'
  FakeWebSocket.instances = []
  FakeWebSocket.pingMode = 'pong'
  ;(globalThis as { WebSocket: unknown }).WebSocket = FakeWebSocket
  $gatewayState.set('idle')
  $desktopBoot.set({
    error: null,
    fakeMode: false,
    message: '',
    phase: 'init',
    progress: 0,
    running: true,
    timestamp: Date.now(),
    visible: true
  })
})

afterEach(() => {
  cleanup()
  takeGatewaySurvivor()?.gateway.close()
  vi.useRealTimers()
  ;(globalThis as { WebSocket: unknown }).WebSocket = originalWebSocket
  delete (window as { hermesDesktop?: unknown }).hermesDesktop
})

it.each(['snapshot', 'events'] as const)(
  'does not fail boot while a local installation is active through %s',
  async source => {
    const pending = deferred<typeof connection>()
    const listeners = new Set<(event: DesktopBootstrapEvent) => void>()
    const desktop = {
      getConnection: vi.fn(() => pending.promise),
      getGatewayWsUrl: vi.fn(async () => connection.wsUrl),
      profile: { get: vi.fn(async () => ({ profile: 'default' })) },
      getBootProgress: vi.fn(async () => ({ running: true, phase: 'init', progress: 0, error: null })),
      onBootProgress: () => () => undefined,
      onBackendExit: () => () => undefined,
      onWindowStateChanged: () => () => undefined,
      getBootstrapState: vi.fn(async () => ({ active: source === 'snapshot', setupChoice: null })),
      onBootstrapEvent: (listener: (event: DesktopBootstrapEvent) => void) => {
        listeners.add(listener)
        return () => listeners.delete(listener)
      }
    }
    ;(window as { hermesDesktop?: unknown }).hermesDesktop = desktop
    const view = render(<Harness />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    if (source === 'events') {
      act(() => listeners.forEach(listener => listener({ type: 'setup-choice', active: true })))
      await act(async () => {
        await vi.advanceTimersByTimeAsync(BACKEND_BOOT_WAIT_TIMEOUT_MS + 1)
      })
      expect($desktopBoot.get().error).toBeNull()
      act(() => listeners.forEach(listener => listener({ type: 'manifest', stages: [], protocolVersion: 1 })))
    }
    // Product preparation can take minutes; the service has not been started yet.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(BACKEND_BOOT_WAIT_TIMEOUT_MS * 3)
    })
    expect($desktopBoot.get().error).toBeNull()
    expect(desktop.getConnection).toHaveBeenCalledTimes(1)
    act(() => listeners.forEach(listener => listener({ type: 'complete', marker: {} })))
    pending.resolve(connection)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect($gatewayState.get()).toBe('open')
    expect($desktopBoot.get().error).toBeNull()
    view.unmount()
    expect(listeners.size).toBe(0)
  }
)
