import { BrowserWindow } from 'electron'

/** One progress envelope for every native update mechanism and app window. */
export function createUpdateProgressEmitter(log: (message: string) => void) {
  return (payload: Record<string, unknown>) => {
    const merged = { stage: 'idle', message: '', percent: null, error: null, ...payload, at: Date.now() }
    log(`[updates] ${merged.stage}: ${merged.message || merged.error || ''}`)
    for (const window of BrowserWindow.getAllWindows()) {
      window.webContents.send('hermes:updates:progress', merged)
    }
  }
}
