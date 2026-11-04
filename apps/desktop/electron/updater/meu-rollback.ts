import { execFile, spawn } from 'node:child_process'
import type { ChildProcess } from 'node:child_process'
import { closeSync, existsSync, openSync } from 'node:fs'
import { readFile, rename, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { setTimeout } from 'node:timers/promises'
import { promisify } from 'node:util'

import type { InstallStamp } from '../install-stamp'
import { ticketRuntimeFor } from '../local-gateway-python'
import type { ResolvedHermesBackend } from '../meu-runtime-upgrade'
import { createMeuWindowsStrategy } from './meu-client'
import { prepareMeuUpdate } from './meu-prepare'
import type { MeuWindowsDeps } from './meu-windows'

const exec = promisify(execFile)
const pointerName = 'active-rollback.json'

const monitors = new Map<string, { directory: string; child: ChildProcess }>()

export interface MeuRollbackOptions {
  root: string
  home: string
  directory: string
  helperDirectory: string
  stamp: Readonly<InstallStamp> | null
  git: string
  executable: string
  resolveBackend: (args: string[]) => Promise<ResolvedHermesBackend>
  log: (message: string) => void
}

interface ManagedMeuOptions
  extends MeuRollbackOptions, Pick<MeuWindowsDeps, 'currentVersion' | 'teardown' | 'restore' | 'emitProgress'> {
  findPython: (root: string) => Promise<string | null>
  isRemote: () => boolean
}

/** Native lifecycle composition stays here; main supplies installation-owned capabilities. */
export function createManagedMeuWindowsStrategy(options: ManagedMeuOptions) {
  let remote = false
  return createMeuWindowsStrategy({
    ...options,
    recoveryDirectory: options.directory,
    prepare: async () => {
      remote = options.isRemote()
    },
    teardown: async () => {
      // The handoff now owns failure recovery before gateway stop or snapshot.
      if (!remote)
        await prepareMeuUpdate({
          ...options,
          fullSnapshot: options.stamp?.meuUpdates?.publicKey ? () => armMeuRollback(options) : undefined
        })
      await options.teardown()
    },
    restore: async () => {
      try {
        await signalMeuRollback(options.home, options.directory, 'cancelled')
      } finally {
        for (const [transaction, monitor] of monitors) {
          if (monitor.directory === options.directory) {
            monitor.child.kill()
            monitors.delete(transaction)
          }
        }
        await options.restore()
      }
    }
  })
}

async function jsonFile(file: string): Promise<Record<string, unknown> | null> {
  try {
    return JSON.parse(await readFile(file, 'utf8'))
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null
    throw error
  }
}

async function writeJson(file: string, value: unknown): Promise<void> {
  await writeFile(file + '.partial', JSON.stringify(value), { mode: 0o600 })
  await rename(file + '.partial', file)
}

/** Start before native handoff, under the old PM runtime and its generation lease. */
export async function armMeuRollback(options: MeuRollbackOptions): Promise<void> {
  if (!options.stamp?.meuUpdates?.publicKey || !existsSync(path.join(options.root, 'hermes_cli', 'main.py'))) return
  const backend = await options.resolveBackend(['gateway', 'stop'])
  if (!backend.command || backend.shell || backend.bootstrap)
    throw new Error('Cannot retain a safe Meu recovery runtime.')
  if (backend.args.slice(-2).join('\0') !== 'gateway\0stop') throw new Error('Invalid Meu recovery command prefix.')
  const runtime = await ticketRuntimeFor({ ...backend, command: backend.command })
  const env = { ...process.env, ...runtime.env, HERMES_HOME: options.home }
  const bootstrap =
    `import os,sys,runpy;os.environ.pop('PYTHONHOME',None);os.environ.pop('PYTHONPATH',None);` +
    `sys.path.insert(0,${JSON.stringify(options.root)});import hermes_bootstrap;` +
    `script=sys.argv.pop(1);sys.argv[0]=script;runpy.run_path(script,run_name='__main__')`
  const { stdout } = await exec(
    runtime.command,
    [
      '-I',
      '-c',
      bootstrap,
      path.join(options.helperDirectory, 'meu_update_recovery.py'),
      '--root',
      options.root,
      '--home',
      options.home,
      '--directory',
      options.directory,
      '--key',
      options.stamp.meuUpdates.publicKey,
      '--git',
      options.git
    ],
    { env, cwd: options.root, windowsHide: true, timeout: 30 * 60_000, maxBuffer: 8 * 1024 * 1024 }
  )
  const { transaction } = JSON.parse(stdout) as { transaction: string }
  validateTransaction(options.home, transaction)
  await exec(runtime.command, [
    '-I', '-c', bootstrap, path.join(options.helperDirectory, 'meu_recovery_runtime.py'),
    '--transaction', transaction
  ], { env, cwd: options.root, windowsHide: true, timeout: 30 * 60_000, maxBuffer: 8 * 1024 * 1024 })
  const journal = await jsonFile(path.join(options.directory, 'meu-update-recovery.json'))
  const commit = (journal?.target as { commit?: string } | undefined)?.commit
  const version = (journal?.target as { version?: string } | undefined)?.version
  if (!commit || !version || !/^[a-f0-9]{40}$/.test(commit))
    throw new Error('Meu recovery target has no valid build identity.')
  const log = openSync(path.join(transaction, 'watch.log'), 'a', 0o600)
  const child = spawn(
    runtime.command,
    [
      '-I',
      '-c',
      bootstrap,
      path.join(transaction, 'meu_update_watch.py'),
      '--durable',
      '--transaction',
      transaction,
      '--parent-pid',
      String(process.pid),
      '--executable',
      options.executable,
      '--launcher',
      backend.command,
      '--launcher-args',
      JSON.stringify(backend.args.slice(0, -2))
    ],
    { env, cwd: options.root, windowsHide: true, detached: true, stdio: ['ignore', log, log] }
  )
  closeSync(log)
  let failure: Error | undefined
  child.on('error', error => {
    failure = error
  })
  monitors.set(transaction, { directory: options.directory, child })
  child.once('exit', () => monitors.delete(transaction))
  child.unref()
  try {
    const deadline = Date.now() + 30_000
    while (Date.now() < deadline) {
      if (failure) throw failure
      const record = await jsonFile(path.join(transaction, 'transaction.json'))
      if (record?.state === 'watching') {
        await writeJson(path.join(options.directory, pointerName), {
          transaction,
          commit,
          version,
          parentPid: process.pid
        })
        options.log('[updates] verified previous installer, profile backup and retained runtime are ready')
        return
      }
      if (record?.state === 'recovery-failed') throw new Error(String(record.error))
      await setTimeout(100)
    }
    throw new Error('Meu recovery monitor did not become ready; update cancelled before handoff.')
  } catch (error) {
    child.kill()
    monitors.delete(transaction)
    throw error
  }
}

function validateTransaction(home: string, transaction: string): void {
  if (
    typeof transaction !== 'string' ||
    path.dirname(path.resolve(transaction)) !== path.resolve(home, 'backups') ||
    !/^meu-update-[a-f0-9]{32}$/.test(path.basename(transaction))
  ) {
    throw new Error('Meu recovery transaction leaves the selected home.')
  }
}

/** Success is published only after the installed app actually reaches its gateway. */
export async function signalMeuRollback(
  home: string,
  directory: string,
  state: 'healthy' | 'failed' | 'cancelled',
  commit?: string,
  version?: string
): Promise<void> {
  const pointer = await jsonFile(path.join(directory, pointerName))
  if (!pointer) return
  if (
    typeof pointer.transaction !== 'string' ||
    typeof pointer.commit !== 'string' ||
    typeof pointer.version !== 'string' ||
    !/^[a-f0-9]{40}$/.test(pointer.commit) ||
    !Number.isSafeInteger(pointer.parentPid)
  ) {
    throw new Error('Invalid Meu recovery startup receipt.')
  }
  validateTransaction(home, pointer.transaction)
  if (
    state === 'cancelled' ? pointer.parentPid !== process.pid : pointer.commit !== commit || pointer.version !== version
  )
    return
  const record = await jsonFile(path.join(pointer.transaction, 'transaction.json'))
  if (record?.state !== 'watching') return
  await writeJson(path.join(pointer.transaction, 'signal.json'), {
    state,
    commit: pointer.commit,
    version: pointer.version
  })
}
