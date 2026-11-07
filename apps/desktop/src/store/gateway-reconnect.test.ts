import { afterEach, describe, expect, it, vi } from 'vitest'

import { reconnectGateway, registerGatewayReconnect } from './gateway-reconnect'

const disposers: Array<() => void> = []

afterEach(() => {
  while (disposers.length > 0) {
    disposers.pop()?.()
  }
})

describe('gateway reconnect controller', () => {
  it('an old disposer cannot remove a new registration of the same handler', async () => {
    const handler = vi.fn()
    const old = registerGatewayReconnect(handler)
    disposers.push(registerGatewayReconnect(handler))
    old()
    await reconnectGateway()
    expect(handler).toHaveBeenCalledOnce()
  })
  it('a new selected route does not reuse the previous routes pending reconnect', async () => {
    let epoch = 1
    let finishA!: () => void
    let finishB!: () => void

    const handler = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<void>(resolve => {
            finishA = resolve
          })
      )
      .mockImplementationOnce(
        () =>
          new Promise<void>(resolve => {
            finishB = resolve
          })
      )

    disposers.push(registerGatewayReconnect(handler, () => epoch))
    const first = reconnectGateway()
    await Promise.resolve()
    epoch = 2
    const second = reconnectGateway()
    await Promise.resolve()
    expect(handler).toHaveBeenCalledTimes(2)
    expect(second).not.toBe(first)
    finishA()
    await first
    expect(reconnectGateway()).toBe(second)
    finishB()
    await second
  })

  it('does not invoke a queued reconnect after selection or registration changes', async () => {
    let epoch = 1
    const old = vi.fn()
    const next = vi.fn()
    disposers.push(registerGatewayReconnect(old, () => epoch))
    const abandoned = reconnectGateway()
    epoch = 2
    disposers.push(registerGatewayReconnect(next, () => epoch))
    await expect(abandoned).rejects.toThrow('Gateway selection changed')
    await reconnectGateway()
    expect(old).not.toHaveBeenCalled()
    expect(next).toHaveBeenCalledOnce()
  })

  it('coalesces repeated requests onto one active reconnect', async () => {
    let finish: (() => void) | undefined

    const handler = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<void>(resolve => {
            finish = resolve
          })
      )
      .mockResolvedValueOnce(undefined)

    disposers.push(registerGatewayReconnect(handler))

    const first = reconnectGateway()
    const second = reconnectGateway()

    expect(second).toBe(first)
    await Promise.resolve()
    expect(handler).toHaveBeenCalledTimes(1)

    finish?.()
    await first

    await reconnectGateway()
    expect(handler).toHaveBeenCalledTimes(2)
  })

  it('only lets the current registration remove itself', async () => {
    const stale = vi.fn()
    const current = vi.fn()
    const disposeStale = registerGatewayReconnect(stale)
    disposers.push(registerGatewayReconnect(current))

    disposeStale()
    await reconnectGateway()

    expect(stale).not.toHaveBeenCalled()
    expect(current).toHaveBeenCalledOnce()
  })

  it('rejects when the gateway boot owner is not mounted', async () => {
    await expect(reconnectGateway()).rejects.toThrow()
  })
})
