import { atom } from 'nanostores'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({ storage: new Map<string, string>(), notify: vi.fn(), apply: vi.fn() }))
vi.mock('@/lib/storage', () => ({
  storedString: (key: string) => state.storage.get(key) ?? null,
  persistString: (key: string, value: string | null) =>
    value === null ? state.storage.delete(key) : state.storage.set(key, value)
}))
vi.mock('@/store/notifications', () => ({ notify: state.notify, dismissNotification: vi.fn() }))
vi.mock('@/store/connections', () => ({ $connectionsRegistry: atom(null), refreshConnectionsRegistry: vi.fn() }))
vi.mock('@/store/session', () => ({ $connection: atom({ mode: 'local' }) }))
vi.mock('@/api/client', () => ({ $apiRequestScope: atom({}), connectionScoped: () => ({}), profileScoped: () => ({}) }))
vi.mock('@/store/gateway-reconnect', () => ({ reconnectGateway: vi.fn() }))
vi.mock('@/hermes', () => ({ checkHermesUpdate: vi.fn(), getActionStatus: vi.fn(), updateHermes: vi.fn() }))

import {
  $updateOverlayOpen,
  $updateStatus,
  BACKGROUND_UPDATE_CHECK_MS,
  startUpdatePoller,
  stopUpdatePoller
} from './updates'

const status = {
  supported: true,
  mechanism: 'electron-updater',
  channel: 'meu-preview',
  currentVersion: '0.1.0-dev.8',
  updateAvailable: true,
  latestTag: 'meu-v0.1.0-dev.9',
  targetSha: 'a'.repeat(40),
  fetchedAt: 1
}
const check = vi.fn()
let previous: Window['hermesDesktop']

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-11-02T12:00:00Z'))
  state.storage.clear()
  state.notify.mockClear()
  state.apply.mockClear()
  check.mockReset().mockResolvedValue(status)
  previous = window.hermesDesktop
  window.hermesDesktop = {
    updates: { check, apply: state.apply, onProgress: vi.fn() }
  } as unknown as Window['hermesDesktop']
  $updateOverlayOpen.set(false)
  $updateStatus.set(null)
})

afterEach(() => {
  stopUpdatePoller()
  window.hermesDesktop = previous
  vi.useRealTimers()
})

it('checks at startup and daily, offers the update and never installs without a click', async () => {
  startUpdatePoller()
  await vi.advanceTimersByTimeAsync(0)
  expect(check).toHaveBeenCalledOnce()
  expect(state.notify).toHaveBeenCalledWith(expect.objectContaining({ id: 'desktop-update-available' }))
  expect($updateOverlayOpen.get()).toBe(false)
  expect(state.apply).not.toHaveBeenCalled()
  const offer = state.notify.mock.calls[0][0]
  offer.action.onClick()
  await vi.advanceTimersByTimeAsync(0)
  expect($updateOverlayOpen.get()).toBe(true)
  expect(state.apply).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(BACKGROUND_UPDATE_CHECK_MS)
  expect(check).toHaveBeenCalledTimes(3)
  expect(state.apply).not.toHaveBeenCalled()
})

it('does not nag after dismissal and treats offline checks as failures rather than claiming to be current', async () => {
  startUpdatePoller()
  await vi.advanceTimersByTimeAsync(0)
  state.notify.mock.calls[0][0].onDismiss()
  state.notify.mockClear()
  window.dispatchEvent(new Event('focus'))
  await vi.advanceTimersByTimeAsync(0)
  expect(state.notify).not.toHaveBeenCalled()
  check.mockRejectedValue(new Error('Offline'))
  await vi.advanceTimersByTimeAsync(BACKGROUND_UPDATE_CHECK_MS)
  expect($updateStatus.get()).toMatchObject({ error: 'check-failed', message: 'Offline' })
  expect(state.apply).not.toHaveBeenCalled()
})
