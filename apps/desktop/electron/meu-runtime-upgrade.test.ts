import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { expect, test } from 'vitest'

import type { InstallStamp } from './install-stamp'
import { needsMeuRuntimeUpgrade, resolveMeuBackendVersion, type ResolvedHermesBackend } from './meu-runtime-upgrade'

test('an existing runnable backend still needs the artifact revision; newer and dirty checkouts are preserved', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'meu-upgrade-'))
  const git = (...args: string[]) =>
    execFileSync('git', ['-C', root, ...args], { encoding: 'utf8', windowsHide: true }).trim()
  try {
    git('init', '-b', 'dev/meu-foundation')
    git('config', 'user.email', 'test@example.invalid')
    git('config', 'user.name', 'Fixture')
    git('remote', 'add', 'origin', 'https://github.com/rodos4312/Meu-Agent.git')
    fs.writeFileSync(path.join(root, 'backend.txt'), 'old')
    git('add', '.')
    git('commit', '-m', 'old')
    const old = git('rev-parse', 'HEAD')
    fs.writeFileSync(path.join(root, 'backend.txt'), 'updated')
    git('commit', '-am', 'new')
    const current = git('rev-parse', 'HEAD')
    const stamp = { commit: current, branch: 'dev/meu-foundation' } as InstallStamp
    expect(await needsMeuRuntimeUpgrade(root, 'git', stamp)).toBe(false)
    expect(await needsMeuRuntimeUpgrade(root, 'git', { ...stamp, commit: old })).toBe(false)
    git('checkout', 'dev/meu-foundation')
    git('reset', '--hard', old)
    expect(await needsMeuRuntimeUpgrade(root, 'git', stamp)).toBe(true)
    const backend = {
      kind: 'command',
      label: 'runnable old backend',
      command: 'hermes',
      args: [],
      bootstrap: false,
      shell: false,
      env: {},
      root
    } as ResolvedHermesBackend
    expect(
      await resolveMeuBackendVersion(backend, {
        appId: 'com.meuagent.desktop',
        isPackaged: true,
        git: 'git',
        root,
        args: ['gateway', 'ensure'],
        stamp
      })
    ).toMatchObject({ kind: 'bootstrap-needed', bootstrap: true, upgrade: true, installStamp: stamp })
    expect(git('rev-parse', 'HEAD')).toBe(old)
    fs.writeFileSync(path.join(root, 'backend.txt'), 'user work')
    await expect(needsMeuRuntimeUpgrade(root, 'git', stamp)).rejects.toThrow('local changes')
    expect(fs.readFileSync(path.join(root, 'backend.txt'), 'utf8')).toBe('user work')
    git('checkout', '-b', 'main')
    await expect(needsMeuRuntimeUpgrade(root, 'git', stamp)).rejects.toThrow('different branch')
    await expect(needsMeuRuntimeUpgrade(root, 'git', null)).rejects.toThrow('build identity')
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})
