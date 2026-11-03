import { createHash } from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, expect, it, vi } from 'vitest'
import type { UpdateCheckResult } from 'electron-updater'

import { MeuWindowsStrategy, type MeuWindowsDeps } from './meu-windows'
import type { MeuRelease } from './meu-release-feed'

const directories: string[] = []
afterEach(() => directories.splice(0).forEach(dir => fs.rmSync(dir, { recursive: true, force: true })))

function fixture() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'meu-update-contract-'))
  directories.push(directory)
  const file = path.join(directory, 'installer.exe')
  const bytes = Buffer.from('not executable; update test fixture only')
  fs.writeFileSync(file, bytes)
  const release: MeuRelease = {
    schema: 1,
    repository: 'rodos4312/Meu-Agent',
    branch: 'dev/meu-foundation',
    channel: 'meu-preview',
    version: '0.1.0-dev.8',
    commit: 'a'.repeat(40),
    publisherName: 'CN=Meu Test Publisher',
    file: 'Meu-0.1.0-dev.8-win-x64.exe',
    size: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
    sha512: createHash('sha512').update(bytes).digest('base64')
  }
  const order: string[] = []
  const native = {
    checkForUpdates: vi.fn(
      async () =>
        ({
          isUpdateAvailable: true,
          updateInfo: {
            version: release.version,
            files: [{ url: release.file, size: release.size, sha512: release.sha512 }]
          }
        }) as UpdateCheckResult
    ),
    downloadUpdate: vi.fn(async () => {
      order.push('download')
      return [file]
    }),
    quitAndInstall: vi.fn(() => {
      order.push('install')
    })
  }
  const deps = {
    currentVersion: '0.1.0-dev.7',
    publisher: release.publisherName,
    findRelease: vi.fn(async () => release),
    native: vi.fn(() => native),
    verifySignature: vi.fn(async () => {
      order.push('signature')
    }),
    retain: vi.fn(async () => {
      order.push('retain')
    }),
    prepare: vi.fn(async () => {
      order.push('prepare')
    }),
    teardown: vi.fn(async () => {
      order.push('stop')
    }),
    restore: vi.fn(async () => {
      order.push('restore')
    }),
    emitProgress: vi.fn()
  } satisfies MeuWindowsDeps
  return { file, release, native, deps, order, strategy: new MeuWindowsStrategy(deps) }
}

it('does not contact a feed or install anything without a pinned signing publisher', async () => {
  const f = fixture()
  const strategy = new MeuWindowsStrategy({ ...f.deps, publisher: null })
  await expect(strategy.check()).resolves.toMatchObject({ supported: false, reason: 'meu-signing-not-configured' })
  await expect(strategy.apply()).rejects.toThrow('signing is not configured')
  expect(f.deps.findRelease).not.toHaveBeenCalled()
})

it('verifies bytes and signature and retains recovery before stopping any backend', async () => {
  const f = fixture()
  await expect(f.strategy.apply()).resolves.toMatchObject({ ok: true, handedOff: true })
  expect(f.order).toEqual(['download', 'signature', 'retain', 'prepare', 'stop', 'install'])
})

it.each(['bytes', 'signature', 'feed', 'busy'] as const)(
  'refuses %s failures before teardown or installation',
  async cause => {
    const f = fixture()
    if (cause === 'bytes') fs.writeFileSync(f.file, 'tampered')
    if (cause === 'signature') f.deps.verifySignature.mockRejectedValue(new Error('Wrong publisher'))
    if (cause === 'feed')
      f.native.checkForUpdates.mockResolvedValue({
        isUpdateAvailable: true,
        updateInfo: { version: '99.0.0', files: [] }
      } as unknown as UpdateCheckResult)
    if (cause === 'busy') f.deps.prepare.mockRejectedValue(new Error('Gateway has active work'))
    await expect(f.strategy.apply()).rejects.toThrow()
    expect(f.deps.teardown).not.toHaveBeenCalled()
    expect(f.native.quitAndInstall).not.toHaveBeenCalled()
    expect(f.deps.restore).not.toHaveBeenCalled()
  }
)

it('restores the running connection when installation fails after teardown', async () => {
  const f = fixture()
  f.native.quitAndInstall.mockImplementation(() => {
    throw new Error('Installer refused')
  })
  await expect(f.strategy.apply()).rejects.toThrow('Installer refused')
  expect(f.deps.restore).toHaveBeenCalledOnce()
  expect(f.order.at(-1)).toBe('restore')
})

it.each(['download', 'recovery cache'] as const)('can retry a failed %s without stopping active work', async stage => {
  const f = fixture()
  if (stage === 'download') f.native.downloadUpdate.mockRejectedValueOnce(new Error('Download interrupted'))
  else f.deps.retain.mockRejectedValueOnce(new Error('Recovery disk full'))
  await expect(f.strategy.apply()).rejects.toThrow()
  expect(f.deps.prepare).not.toHaveBeenCalled()
  expect(f.deps.teardown).not.toHaveBeenCalled()
  expect(f.native.quitAndInstall).not.toHaveBeenCalled()
  await expect(f.strategy.apply()).resolves.toMatchObject({ ok: true, handedOff: true })
})
