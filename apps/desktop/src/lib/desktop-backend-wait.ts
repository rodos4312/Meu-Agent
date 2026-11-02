import type { DesktopBootstrapEvent } from '@/global'

import { BACKEND_BOOT_WAIT_TIMEOUT_MS, TimeoutError } from './with-timeout'

type BootstrapBridge = Partial<Pick<Window['hermesDesktop'], 'getBootstrapState' | 'onBootstrapEvent'>>

/** Installation and the user's setup choice have their own progress/cancel UI.
 * Start the service readiness budget only once that preparation has finished. */
export function waitForDesktopBackend<T>(
  start: () => Promise<T>,
  desktop: BootstrapBridge,
  message: string,
  signal: AbortSignal
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    let timer: ReturnType<typeof setTimeout> | undefined
    let settled = false
    let revision = 0
    let off: (() => void) | undefined

    const settle = (publish: () => void) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      off?.()
      signal.removeEventListener('abort', abort)
      publish()
    }
    const abort = () => settle(() => reject(signal.reason))
    const arm = (installing: boolean) => {
      if (settled) return
      clearTimeout(timer)
      if (!installing) {
        timer = setTimeout(() => settle(() => reject(new TimeoutError(message))), BACKEND_BOOT_WAIT_TIMEOUT_MS)
      }
    }
    const onEvent = (event: DesktopBootstrapEvent) => {
      switch (event.type) {
        case 'manifest':
        case 'stage':
          revision += 1
          arm(true)
          break
        case 'setup-choice':
          revision += 1
          arm(event.active)
          break
        case 'complete':
        case 'dismissed':
          revision += 1
          arm(false)
          break
        case 'failed':
          revision += 1
          settle(() => reject(new Error(event.error)))
          break
      }
    }

    arm(false)
    off = desktop.onBootstrapEvent?.(onEvent)
    signal.addEventListener('abort', abort, { once: true })
    if (signal.aborted) {
      abort()
      return
    }
    // Subscribe first: a delayed snapshot must not undo a newer install event.
    void desktop.getBootstrapState?.().then(
      snapshot => {
        if (revision === 0) arm(snapshot.active || Boolean(snapshot.setupChoice))
      },
      () => undefined
    )
    try {
      start().then(
        value => settle(() => resolve(value)),
        error => settle(() => reject(error))
      )
    } catch (error) {
      settle(() => reject(error))
    }
  })
}
