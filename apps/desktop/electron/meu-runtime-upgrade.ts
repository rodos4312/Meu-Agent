import { execFile } from 'node:child_process'
import { promisify } from 'node:util'

import type { InstallStamp } from './install-stamp'

const exec = promisify(execFile)
const BRANCH = 'dev/meu-foundation'
const REPOSITORY = 'https://github.com/rodos4312/Meu-Agent.git'
const PRIVATE_REPOSITORY = 'https://github.com/rodos4312/Meu-Agent-RC-private.git'

export function sourceSeedForStamp(stamp: Readonly<InstallStamp> | null) {
  const seed = stamp?.sourceSeed
  if (!seed) return null
  if (seed.schema !== 1 || seed.file !== 'meu-source-seed.zip' || seed.commit !== stamp.commit ||
      !/^[a-f0-9]{40}$/.test(seed.commit) || !/^[a-f0-9]{40}$/.test(seed.base) ||
      seed.branch !== BRANCH || ![REPOSITORY, PRIVATE_REPOSITORY].includes(seed.repository) ||
      !/^[a-f0-9]{64}$/.test(seed.sha256) || !Number.isSafeInteger(seed.size) || seed.size <= 0 || seed.size > 512 * 1024 * 1024) {
    throw new Error('Meu source package does not match the installed application.')
  }
  return seed
}

/** Compare actual checkout identity with this artifact, never the mutable install marker. */
export async function needsMeuRuntimeUpgrade(root: string, git: string, stamp: Readonly<InstallStamp> | null) {
  const seed = sourceSeedForStamp(stamp)
  if (!stamp?.commit || !/^[a-f0-9]{40}$/.test(stamp.commit) || (!seed && stamp.branch !== BRANCH)) {
    throw new Error('Meu cannot verify the backend version: this installer has no valid development build identity.')
  }

  const run = async (...args: string[]) =>
    (
      await exec(git, ['-C', root, ...args], {
        windowsHide: true,
        timeout: 120_000,
        maxBuffer: 1024 * 1024,
        env: { ...process.env, GIT_TERMINAL_PROMPT: '0', GCM_INTERACTIVE: 'never' }
      })
    ).stdout.trim()

  const current = await run('rev-parse', 'HEAD')

  if (current === stamp.commit) {
    return false
  }

  const branch = await run('branch', '--show-current')
  const remote = await run('config', '--get', 'remote.origin.url')

  if ((branch && branch !== BRANCH) || ![REPOSITORY, ...(seed ? [PRIVATE_REPOSITORY] : [])].includes(remote.replace(/\/$/, ''))) {
    throw new Error('Meu backend upgrade stopped: the installed checkout uses a different branch or repository.')
  }

  if (await run('status', '--porcelain')) {
    throw new Error('Meu backend upgrade stopped: the installed source has local changes. Keep them before updating.')
  }

  try {
    await run('cat-file', '-e', `${stamp.commit}^{commit}`)
  } catch {
    // The verified local source package owns this pin. Its repository stage
    // checks ancestry before advancing; never ask a private GitHub for login.
    if (seed) return true
    await run('fetch', '--no-tags', 'origin', BRANCH)
  }

  try {
    await run('merge-base', '--is-ancestor', stamp.commit, current)

    return false // An older desktop must never downgrade a newer backend.
  } catch {
    /* The artifact may be ahead; prove that before changing anything. */
  }

  try {
    await run('merge-base', '--is-ancestor', current, stamp.commit)
  } catch {
    throw new Error('Meu backend and installer histories differ. Automatic upgrade cannot safely continue.')
  }

  return true
}

export interface ResolvedHermesBackend {
  kind: string
  label: string
  command: string | null
  args: string[]
  env: NodeJS.ProcessEnv
  bootstrap: boolean
  shell: boolean
  local?: 'none' | 'installed' | 'bundled'
  root?: string
  ticketCommand?: string
  ticketEnv?: NodeJS.ProcessEnv
  installStamp?: Readonly<InstallStamp> | null
  activeRoot?: string
  isPackaged?: boolean
  platform?: NodeJS.Platform
  readyFile?: boolean
  upgrade?: boolean
}

export function meuUpgradeBackend(
  args: string[],
  activeRoot: string,
  stamp: Readonly<InstallStamp> | null
): ResolvedHermesBackend {
  return {
    kind: 'bootstrap-needed',
    label: 'Updating Meu backend',
    command: null,
    args,
    bootstrap: true,
    env: {},
    shell: false,
    activeRoot,
    installStamp: stamp,
    upgrade: true,
    local: 'none'
  }
}

export async function resolveMeuBackendVersion(
  backend: ResolvedHermesBackend,
  options: {
    appId: string
    isPackaged: boolean
    git: string
    root: string
    args: string[]
    stamp: Readonly<InstallStamp> | null
  }
): Promise<ResolvedHermesBackend> {
  if (
    options.appId === 'com.meuagent.desktop' &&
    options.isPackaged &&
    (await needsMeuRuntimeUpgrade(options.root, options.git, options.stamp))
  ) {
    return meuUpgradeBackend(options.args, options.root, options.stamp)
  }

  return backend
}
