import fs from 'node:fs'
import path from 'node:path'
import { INSTALL_STAMP, installShape, type InstallStamp } from './install-stamp'

export function bootstrapSnapshot<State>(
  state: State,
  stamp: Readonly<InstallStamp> | null = INSTALL_STAMP
): State & { bundled: boolean } {
  return { ...state, bundled: installShape(stamp) === 'bundled' }
}


/** Source completion (or the pinned installer) owns this runtime identity. */
export function readCanonicalInstallStamp(root: string) {
  try {
    const parsed = JSON.parse(fs.readFileSync(path.join(root, 'install-stamp.json'), 'utf8'))
    return parsed && typeof parsed === 'object' && typeof parsed.source === 'string' ? parsed : null
  } catch { return null }
}
