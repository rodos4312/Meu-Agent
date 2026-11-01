import { describe, expect, it, vi } from 'vitest'
import { BootstrapSingleFlight } from './bootstrap-single-flight'

describe('first-run installation single-flight', () => {
  it('reuses one in-flight install across concurrent reconnects', async () => {
    const flight = new BootstrapSingleFlight<number>()
    let finish: (value: number) => void = () => { throw new Error('not started') }
    const starter = vi.fn(() => new Promise<number>(resolve => { finish = resolve }))
    const first = flight.run(starter)
    const second = flight.run(starter)
    expect(first).toBe(second)
    expect(flight.isRunning()).toBe(true)
    await Promise.resolve()
    expect(starter).toHaveBeenCalledTimes(1)
    finish(42)
    expect(await first).toBe(42)
    expect(await second).toBe(42)
    expect(flight.isRunning()).toBe(false)
  })

  it('allows a new install after a failed run finishes', async () => {
    const flight = new BootstrapSingleFlight<string>()
    await expect(flight.run(async () => { throw new Error('install failed') })).rejects.toThrow('install failed')
    expect(flight.isRunning()).toBe(false)
    await expect(flight.run(async () => 'repaired')).resolves.toBe('repaired')
  })
})
