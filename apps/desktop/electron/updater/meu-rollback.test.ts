import { mkdtemp, mkdir, readFile, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { describe, expect, it, vi } from 'vitest'

interface Lifecycle {
  prepare: () => Promise<void>
  teardown: () => Promise<void>
  restore: () => Promise<void>
}
const { client, prepare } = vi.hoisted(() => ({
  client: vi.fn((options: Lifecycle) => Promise.resolve(options)),
  prepare: vi.fn(async () => undefined)
}))
vi.mock('./meu-client', () => ({ createMeuWindowsStrategy: client }))
vi.mock('./meu-prepare', () => ({ prepareMeuUpdate: prepare }))

import { createManagedMeuWindowsStrategy, signalMeuRollback } from './meu-rollback'

async function receipt() {
  const home = await mkdtemp(path.join(os.tmpdir(), 'meu-receipt-'))
  const directory = path.join(home, 'cache')
  const transaction = path.join(home, 'backups', 'meu-update-' + 'a'.repeat(32))
  await mkdir(directory)
  await mkdir(transaction, { recursive: true })
  const commit = 'b'.repeat(40)
  const version = '0.1.0-dev.17'
  await writeFile(
    path.join(directory, 'active-rollback.json'),
    JSON.stringify({ transaction, commit, version, parentPid: process.pid })
  )
  await writeFile(path.join(transaction, 'transaction.json'), JSON.stringify({ state: 'watching' }))
  return { home, directory, transaction, commit, version }
}

describe('Meu startup recovery acknowledgement', () => {
  it('accepts success only for the exact target commit AND desktop version', async () => {
    const r = await receipt()
    const signal = path.join(r.transaction, 'signal.json')
    await signalMeuRollback(r.home, r.directory, 'healthy', r.commit, '0.1.0-dev.16')
    await expect(readFile(signal)).rejects.toMatchObject({ code: 'ENOENT' })
    await signalMeuRollback(r.home, r.directory, 'healthy', 'c'.repeat(40), r.version)
    await expect(readFile(signal)).rejects.toMatchObject({ code: 'ENOENT' })
    await signalMeuRollback(r.home, r.directory, 'healthy', r.commit, r.version)
    expect(JSON.parse(await readFile(signal, 'utf8'))).toEqual({
      state: 'healthy',
      commit: r.commit,
      version: r.version
    })
  })

  it('refuses a pointer into a different profile', async () => {
    const r = await receipt()
    await expect(
      signalMeuRollback(path.join(r.home, 'profiles', 'other'), r.directory, 'failed', r.commit, r.version)
    ).rejects.toThrow('selected home')
    await expect(readFile(path.join(r.transaction, 'signal.json'))).rejects.toMatchObject({ code: 'ENOENT' })
  })

  it('does not overwrite a completed recovery or allow another parent to cancel', async () => {
    const r = await receipt()
    await writeFile(
      path.join(r.directory, 'active-rollback.json'),
      JSON.stringify({ ...r, parentPid: process.pid + 1 })
    )
    await signalMeuRollback(r.home, r.directory, 'cancelled')
    await expect(readFile(path.join(r.transaction, 'signal.json'))).rejects.toMatchObject({ code: 'ENOENT' })
    await writeFile(path.join(r.transaction, 'transaction.json'), JSON.stringify({ state: 'rolled-back' }))
    await signalMeuRollback(r.home, r.directory, 'healthy', r.commit, r.version)
    await expect(readFile(path.join(r.transaction, 'signal.json'))).rejects.toMatchObject({ code: 'ENOENT' })
  })
})

it('keeps local preparation inside the recoverable handoff and never stops local work for a remote client', async () => {
  for (const remote of [false, true]) {
    client.mockClear()
    prepare.mockClear()
    const r = await receipt()
    const teardown = vi.fn(async () => undefined)
    await createManagedMeuWindowsStrategy({
      ...r,
      root: r.home,
      helperDirectory: r.home,
      stamp: null,
      git: 'git',
      executable: process.execPath,
      currentVersion: '0.1.0-dev.16',
      resolveBackend: vi.fn(),
      findPython: vi.fn(),
      log: vi.fn(),
      isRemote: () => remote,
      teardown,
      restore: vi.fn(async () => undefined),
      emitProgress: vi.fn()
    })
    const lifecycle = client.mock.calls[0][0]
    await lifecycle.prepare()
    expect(prepare).not.toHaveBeenCalled()
    await lifecycle.teardown()
    expect(prepare).toHaveBeenCalledTimes(remote ? 0 : 1)
    expect(teardown).toHaveBeenCalledOnce()
  }
})
