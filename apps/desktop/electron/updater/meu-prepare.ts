import { execFile } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { promisify } from 'node:util'

import type { ResolvedHermesBackend } from '../meu-runtime-upgrade'
import { readPreUpdateBackupEnabled } from '../pre-update-backup-config'
import { resolveInstallationLauncher } from '../updater-process'

import { preflightStateDb } from './state-db-preflight'

const exec = promisify(execFile)

export interface MeuPrepareDeps {
  root: string
  home: string
  resolveBackend: (args: string[]) => Promise<ResolvedHermesBackend>
  findPython: (root: string) => Promise<string | null>
  log: (message: string) => void
}

/** Preserve existing backup preferences and the canonical gateway's busy refusal. */
export async function prepareMeuUpdate(deps: MeuPrepareDeps): Promise<void> {
  // A gateway-only client has no local installation to snapshot or stop.
  if (!fs.existsSync(path.join(deps.root, 'hermes_cli', 'main.py'))) {
    return
  }

  if (
    await readPreUpdateBackupEnabled(
      deps.resolveBackend(['config', 'get', 'updates.pre_update_backup', '--json']),
      deps.home
    )
  ) {
    const managed = fs.existsSync(path.join(deps.root, 'pm'))
    const launcher = managed ? resolveInstallationLauncher(deps.root, true, deps.home) : null

    if (managed && !launcher) {
      throw new Error('Meu installation launcher is missing; repair before updating.')
    }

    await preflightStateDb({
      home: deps.home,
      log: deps.log,
      launcher,
      python: managed ? null : await deps.findPython(deps.root),
      script: path.join(deps.root, 'hermes_cli', 'backup_sqlite.py')
    })
  }

  const backend = await deps.resolveBackend(['gateway', 'stop'])

  if (!backend.command || backend.bootstrap || backend.shell) {
    throw new Error('Cannot safely stop this Meu backend for an update.')
  }

  await exec(backend.command, backend.args, {
    env: { ...process.env, ...backend.env, HERMES_HOME: deps.home },
    cwd: deps.root,
    windowsHide: true,
    timeout: 60_000,
    maxBuffer: 1024 * 1024
  })
}
