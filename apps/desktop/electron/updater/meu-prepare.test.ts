import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { beforeEach, expect, it, vi } from 'vitest'

const { backupEnabled, snapshot } = vi.hoisted(() => ({ backupEnabled: vi.fn(async () => false), snapshot: vi.fn() }))
vi.mock('../pre-update-backup-config', () => ({ readPreUpdateBackupEnabled: backupEnabled }))
vi.mock('./state-db-preflight', () => ({ preflightStateDb: snapshot }))

import type { ResolvedHermesBackend } from '../meu-runtime-upgrade'

import { prepareMeuUpdate } from './meu-prepare'

beforeEach(() => vi.clearAllMocks())

it('stops the selected home with the inherited OS environment even when the resolver returns only overrides', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'meu-stop-home-'))
  const home = path.join(root, 'Meu data')
  const receipt = path.join(root, 'stopped.json')

  try {
    fs.mkdirSync(path.join(root, 'hermes_cli'))
    fs.writeFileSync(path.join(root, 'hermes_cli', 'main.py'), '# fixture')

    const resolveBackend = vi.fn(async (): Promise<ResolvedHermesBackend> => ({
      kind: 'fixture', label: 'CLI fixture', command: process.execPath,
      args: ['-e', `require('node:fs').writeFileSync(${JSON.stringify(receipt)}, JSON.stringify({home:process.env.HERMES_HOME, os:process.env.SystemRoot || process.env.HOME, marker:process.env.MEU_TEST_OVERRIDE}))`],
      env: { HERMES_HOME: path.join(root, 'wrong home'), MEU_TEST_OVERRIDE: 'preserved' },
      root, bootstrap: false, shell: false
    }))

    await prepareMeuUpdate({ root, home, resolveBackend, findPython: vi.fn(), log: vi.fn() })
    expect(JSON.parse(fs.readFileSync(receipt, 'utf8'))).toEqual({
      home, os: process.env.SystemRoot || process.env.HOME, marker: 'preserved'
    })
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

it('preserves the canonical gateway busy refusal and never adds force or changes the saved backup preference', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'meu-update-prepare-'))

  try {
    fs.mkdirSync(path.join(root, 'hermes_cli'))
    fs.writeFileSync(path.join(root, 'hermes_cli', 'main.py'), '# source identity fixture; never executed')

    const resolveBackend = vi.fn(async (args: string[]): Promise<ResolvedHermesBackend> => ({
      kind: 'fixture',
      label: 'Meu test CLI',
      command: process.execPath,
      args: ['-e', "process.stderr.write('Gateway has active work');process.exit(17)"],
      env: process.env,
      root,
      bootstrap: false,
      shell: false
    }))

    await expect(
      prepareMeuUpdate({ root, home: root, resolveBackend, findPython: vi.fn(), log: vi.fn() })
    ).rejects.toThrow('active work')
    expect(resolveBackend).toHaveBeenLastCalledWith(['gateway', 'stop'])
    expect(snapshot).not.toHaveBeenCalled()
    expect(backupEnabled).toHaveBeenCalledOnce()
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

it('does not bootstrap or stop a local gateway for a client with no local installation', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'meu-update-remote-client-'))

  try {
    const resolveBackend = vi.fn()
    await prepareMeuUpdate({ root, home: root, resolveBackend, findPython: vi.fn(), log: vi.fn() })
    expect(resolveBackend).not.toHaveBeenCalled()
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})
