import { ipcMain } from 'electron'

import type { UpdaterApplyResultWire, UpdaterStrategy } from './updater/index'

export interface DesktopSharedMetrics {
  noteUpdateProgress(stage: string): void
  trackUpdateApply(packaged: UpdaterStrategy | null, strategy: UpdaterStrategy): Promise<UpdaterApplyResultWire>
  recordRendererGone(windowId: number, reason: unknown): void
}

/** Retain the preload contract without collecting startup, update or crash metrics. */
export function registerDesktopSharedMetrics(): DesktopSharedMetrics {
  for (const channel of [
    'hermes:startup-latency:claim',
    'hermes:updates:metric:take',
    'hermes:desktop-metrics:crash:take'
  ]) {
    ipcMain.handle(channel, () => null)
  }

  for (const channel of [
    'hermes:updates:metric:ack',
    'hermes:desktop-metrics:set-enabled',
    'hermes:desktop-metrics:crash:ack'
  ]) {
    ipcMain.handle(channel, () => undefined)
  }

  return {
    recordRendererGone: () => undefined,
    noteUpdateProgress: () => undefined,
    trackUpdateApply: (_packaged, strategy) => strategy.apply()
  }
}
