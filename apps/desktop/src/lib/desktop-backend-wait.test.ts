import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import type { DesktopBootstrapEvent, DesktopBootstrapState } from '@/global'

import { deferred } from '../test/deferred'
import { waitForDesktopBackend } from './desktop-backend-wait'
import { BACKEND_BOOT_WAIT_TIMEOUT_MS } from './with-timeout'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

function fixture() {
  const pending = deferred<string>()
  const snapshot = deferred<DesktopBootstrapState>()
  const listeners = new Set<(event: DesktopBootstrapEvent) => void>()
  const abort = new AbortController()
  const bridge = {
    getBootstrapState: () => snapshot.promise,
    onBootstrapEvent: (listener: (event: DesktopBootstrapEvent) => void) => {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    }
  }
  const result = waitForDesktopBackend(() => pending.promise, bridge, 'Service timed out', abort.signal)
  return {
    pending,
    snapshot,
    listeners,
    abort,
    result,
    emit: (event: DesktopBootstrapEvent) => listeners.forEach(l => l(event))
  }
}

it('keeps a bounded readiness wait when no installer is active', async () => {
  const f = fixture()
  const failed = expect(f.result).rejects.toThrow('Service timed out')
  await vi.advanceTimersByTimeAsync(BACKEND_BOOT_WAIT_TIMEOUT_MS)
  await failed
  expect(f.listeners.size).toBe(0)
})

it('starts a fresh bounded service wait after a long installation completes', async () => {
  const f = fixture()
  const failed = expect(f.result).rejects.toThrow('Service timed out')
  f.emit({ type: 'manifest', stages: [], protocolVersion: 1 })
  await vi.advanceTimersByTimeAsync(BACKEND_BOOT_WAIT_TIMEOUT_MS * 4)
  expect(f.listeners.size).toBe(1)
  f.emit({ type: 'complete', marker: {} })
  await vi.advanceTimersByTimeAsync(BACKEND_BOOT_WAIT_TIMEOUT_MS - 1)
  expect(f.listeners.size).toBe(1)
  await vi.advanceTimersByTimeAsync(1)
  await failed
  expect(f.listeners.size).toBe(0)
})

it('does not let a stale snapshot undo a newer installation event', async () => {
  const f = fixture()
  f.emit({ type: 'manifest', stages: [], protocolVersion: 1 })
  f.snapshot.resolve({ active: false, setupChoice: null } as DesktopBootstrapState)
  await vi.advanceTimersByTimeAsync(BACKEND_BOOT_WAIT_TIMEOUT_MS * 2)
  f.pending.resolve('ready')
  await expect(f.result).resolves.toBe('ready')
  expect(f.listeners.size).toBe(0)
})

it('reports installer failure immediately and cleans up', async () => {
  const f = fixture()
  const failed = expect(f.result).rejects.toThrow('Download failed')
  f.emit({ type: 'manifest', stages: [], protocolVersion: 1 })
  f.emit({ type: 'failed', error: 'Download failed' })
  await failed
  expect(f.listeners.size).toBe(0)
})

it('releases a setup-choice listener when its window unmounts', async () => {
  const f = fixture()
  const failed = expect(f.result).rejects.toThrow('Window closed')
  f.emit({ type: 'setup-choice', active: true })
  await vi.advanceTimersByTimeAsync(BACKEND_BOOT_WAIT_TIMEOUT_MS * 2)
  f.abort.abort(new Error('Window closed'))
  await failed
  expect(f.listeners.size).toBe(0)
  expect(vi.getTimerCount()).toBe(0)
})

it('does not revive timers when a snapshot arrives after the connection is ready', async () => {
  const f = fixture()
  f.pending.resolve('ready')
  await expect(f.result).resolves.toBe('ready')
  f.snapshot.resolve({ active: false, setupChoice: null } as DesktopBootstrapState)
  await vi.advanceTimersByTimeAsync(0)
  expect(vi.getTimerCount()).toBe(0)
})
