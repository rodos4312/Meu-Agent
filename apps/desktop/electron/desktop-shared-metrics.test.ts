import { expect, it, vi } from 'vitest'

const handlers = new Map<string, (...args: unknown[]) => unknown>()

vi.mock('electron', () => ({
  ipcMain: { handle: (channel: string, fn: (...args: unknown[]) => unknown) => handlers.set(channel, fn) }
}))

const { registerDesktopSharedMetrics } = await import('./desktop-shared-metrics')

it('keeps telemetry IPC inert while updates still apply and propagate errors', async () => {
  const metrics = registerDesktopSharedMetrics()
  const result = { ok: true, handedOff: false }
  const apply = vi.fn(async () => result)
  const strategy = { mechanism: 'electron-updater', apply } as never

  expect(await metrics.trackUpdateApply(strategy, strategy)).toBe(result)
  expect(apply).toHaveBeenCalledTimes(1)
  metrics.noteUpdateProgress('download')
  metrics.recordRendererGone(1, 'crashed')
  handlers.get('hermes:desktop-metrics:set-enabled')!({}, true, 'legacy')

  for (const channel of ['hermes:startup-latency:claim', 'hermes:updates:metric:take', 'hermes:desktop-metrics:crash:take']) {
    expect(handlers.get(channel)!({})).toBeNull()
  }

  const failure = new Error('apply failed')
  const broken = { apply: async () => { throw failure } } as never

  await expect(metrics.trackUpdateApply(broken, broken)).rejects.toBe(failure)
})
