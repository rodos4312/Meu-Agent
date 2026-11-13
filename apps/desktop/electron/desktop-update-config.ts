import fs from 'node:fs'

/**
 * The desktop updater's own settings file (`<userData>/updates.json`): `branch` for source checkouts and
 * `channel` for the Meu stable/RC preference (see electron/updater/meu-channel.ts). Every other key survives
 * a write.
 */
function readObject(file: string): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(fs.readFileSync(file, 'utf8'))

    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : {}
  } catch {
    return {}
  }
}

export function readDesktopUpdateBranch(file: string, fallback: string): { branch: string; branchExplicit: boolean } {
  const value = readObject(file).branch
  const branch = typeof value === 'string' ? value.trim() : ''

  return { branch: branch || fallback, branchExplicit: branch.length > 0 }
}

/** Absent or unreadable means "no saved preference": the build keeps its own channel. */
export function readMeuChannelPreference(file: string): unknown {
  return readObject(file).channel
}

/** Atomic (temp + rename) so a crash never leaves a half-written settings file. */
export function writeMeuChannelPreference(file: string, channel: 'stable' | 'rc'): void {
  const temporary = `${file}.tmp`
  fs.writeFileSync(temporary, JSON.stringify({ ...readObject(file), channel }, null, 2), 'utf8')
  fs.renameSync(temporary, file)
}
