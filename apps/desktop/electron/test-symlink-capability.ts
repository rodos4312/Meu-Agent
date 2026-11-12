/**
 * Whether this host lets the test process create symbolic links. Windows refuses them without
 * Developer Mode or elevation (EPERM), so tests whose fixture IS a symlink run only where links
 * can exist; the containment logic they cover still runs everywhere links can be made.
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

function probe(): boolean {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-symlink-probe-'))

  try {
    fs.writeFileSync(path.join(dir, 'target'), '')
    fs.symlinkSync(path.join(dir, 'target'), path.join(dir, 'link'))

    return true
  } catch {
    return false
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
}

export const canCreateSymlinks: boolean = probe()
