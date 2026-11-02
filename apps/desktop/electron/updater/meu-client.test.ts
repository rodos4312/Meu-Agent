import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createHash, generateKeyPairSync } from 'node:crypto'
import { beforeEach, expect, it, vi } from 'vitest'

const { verify, native, construct, listeners, findRelease } = vi.hoisted(() => {
  const listeners = new Map<string, (error: Error) => void>()
  const native = {
    on: vi.fn((name: string, fn: (error: Error) => void) => listeners.set(name, fn)),
    checkForUpdates: vi.fn(),
    downloadUpdate: vi.fn(),
    quitAndInstall: vi.fn(),
    verifyUpdateCodeSignature: undefined
  }
  return { verify: vi.fn(async () => undefined), native, construct: vi.fn(), listeners, findRelease: vi.fn() }
})
vi.mock(import('./meu-release-feed'), async original => ({ ...(await original()), findMeuRelease: findRelease }))
vi.mock('./meu-signature', () => ({ verifyMeuSignature: verify }))
vi.mock('electron-updater', () => ({
  default: {
    NsisUpdater: class {
      constructor(options: unknown) {
        construct(options)
        return native
      }
    }
  }
}))

import { createMeuWindowsStrategy } from './meu-client'
import type { InstallStamp } from '../install-stamp'
import signing from '../../meu-release-signing.cjs'

beforeEach(() => {
  vi.clearAllMocks()
  listeners.clear()
})

it('offers free-key updates without initializing downloads and rejects tampering before stopping active work', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'meu-free-client-'))
  try {
    const file = path.join(root, 'fixture.exe')
    const bytes = Buffer.from('nonexecutable cached installer fixture')
    fs.writeFileSync(file, bytes)
    const keys = generateKeyPairSync('ed25519')
    const publicKey = keys.publicKey.export({ format: 'der', type: 'spki' }).toString('base64')
    const release = signing.signRelease(
      {
        schema: 2,
        repository: 'rodos4312/Meu-Agent',
        branch: 'dev/meu-foundation',
        channel: 'meu-preview',
        publisherName: '',
        version: '0.1.0-dev.9',
        commit: 'a'.repeat(40),
        file: 'Meu-0.1.0-dev.9-win-x64.exe',
        size: bytes.length,
        sha256: createHash('sha256').update(bytes).digest('hex'),
        sha512: createHash('sha512').update(bytes).digest('base64')
      },
      keys.privateKey,
      publicKey
    )
    findRelease.mockResolvedValue(release)
    native.checkForUpdates.mockResolvedValue({
      isUpdateAvailable: true,
      updateInfo: {
        version: release.version,
        files: [{ url: release.file, sha512: release.sha512, size: release.size }]
      }
    })
    native.downloadUpdate.mockResolvedValue([file])
    const teardown = vi.fn()
    const strategy = await createMeuWindowsStrategy({
      stamp: {
        meuUpdates: { repository: release.repository, branch: release.branch, channel: release.channel, publicKey }
      } as InstallStamp,
      currentVersion: '0.1.0-dev.8',
      executable: 'unused.exe',
      recoveryDirectory: path.join(root, 'retained'),
      prepare: vi.fn(),
      teardown,
      restore: vi.fn(),
      emitProgress: vi.fn(),
      log: vi.fn()
    })
    await expect(strategy.check()).resolves.toMatchObject({ supported: true, updateAvailable: true })
    expect(construct).not.toHaveBeenCalled()
    expect(native.downloadUpdate).not.toHaveBeenCalled()
    await expect(strategy.apply()).resolves.toMatchObject({ ok: true, handedOff: true })
    expect(native.quitAndInstall).toHaveBeenCalledWith(true, true)
    expect(native).toMatchObject({
      autoDownload: false,
      autoInstallOnAppQuit: false,
      disableDifferentialDownload: true
    })
    expect(verify).not.toHaveBeenCalled()
    teardown.mockClear()
    native.quitAndInstall.mockClear()
    findRelease.mockResolvedValue({ ...release, signature: Buffer.alloc(64).toString('base64') })
    await expect(strategy.apply()).rejects.toThrow('signature')
    expect(teardown).not.toHaveBeenCalled()
    expect(native.quitAndInstall).not.toHaveBeenCalled()
    findRelease.mockResolvedValue(release)
    fs.writeFileSync(file, Buffer.alloc(bytes.length))
    await expect(strategy.apply()).rejects.toThrow('digest')
    expect(teardown).not.toHaveBeenCalled()
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

it('unsigned builds never initialize a native updater or check a remote feed', async () => {
  const strategy = await createMeuWindowsStrategy({
    stamp: null,
    currentVersion: '0.1.0-dev.7',
    executable: 'Meu.exe',
    recoveryDirectory: 'unused',
    log: vi.fn(),
    prepare: vi.fn(),
    teardown: vi.fn(),
    restore: vi.fn(),
    emitProgress: vi.fn()
  })
  await expect(strategy.check()).resolves.toMatchObject({ supported: false })
  expect(construct).not.toHaveBeenCalled()
  expect(verify).not.toHaveBeenCalled()
  expect(findRelease).not.toHaveBeenCalled()
})

it('uses only the pinned Meu feed and restores only after an asynchronous installer failure', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'meu-native-client-'))
  try {
    const file = path.join(root, 'fixture.exe')
    const bytes = Buffer.from('never executed; native updater fixture')
    fs.writeFileSync(file, bytes)
    const release = {
      schema: 1,
      repository: 'rodos4312/Meu-Agent',
      branch: 'dev/meu-foundation',
      channel: 'meu-preview',
      publisherName: 'CN=Meu Test Publisher',
      version: '0.1.0-dev.8',
      commit: 'a'.repeat(40),
      file: 'Meu-0.1.0-dev.8-win-x64.exe',
      size: bytes.length,
      sha256: createHash('sha256').update(bytes).digest('hex'),
      sha512: createHash('sha512').update(bytes).digest('base64')
    }
    findRelease.mockResolvedValue(release)
    native.checkForUpdates.mockResolvedValue({
      isUpdateAvailable: true,
      updateInfo: {
        version: release.version,
        files: [{ url: release.file, sha512: release.sha512, size: release.size }]
      }
    })
    native.downloadUpdate.mockResolvedValue([file])
    const restore = vi.fn(async () => undefined)
    const strategy = await createMeuWindowsStrategy({
      stamp: { meuUpdates: release } as unknown as InstallStamp,
      currentVersion: '0.1.0-dev.7',
      executable: path.join(root, 'current.exe'),
      recoveryDirectory: path.join(root, 'retained'),
      log: vi.fn(),
      prepare: vi.fn(),
      teardown: vi.fn(),
      restore,
      emitProgress: vi.fn()
    })
    await strategy.apply()
    expect(construct).toHaveBeenCalledWith({
      provider: 'generic',
      channel: 'meu-preview',
      url: 'https://github.com/rodos4312/Meu-Agent/releases/download/meu-v0.1.0-dev.8/'
    })
    expect(native).toMatchObject({
      autoDownload: false,
      autoInstallOnAppQuit: false,
      allowDowngrade: false,
      disableWebInstaller: true,
      requestHeaders: { 'x-user-staging-id': '' }
    })
    expect(restore).not.toHaveBeenCalled()
    listeners.get('error')?.(new Error('Native installer refused'))
    await Promise.resolve()
    expect(restore).toHaveBeenCalledOnce()
    expect(verify).toHaveBeenCalledWith(file, release.publisherName, release.version)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

it('a foreign update authority is refused before inspecting any executable', async () => {
  const stamp = {
    meuUpdates: {
      repository: 'NousResearch/hermes-agent',
      branch: 'main',
      channel: 'latest',
      publisherName: 'CN=Other'
    }
  } as InstallStamp
  await expect(
    createMeuWindowsStrategy({
      stamp,
      currentVersion: '0.1.0-dev.7',
      executable: 'Meu.exe',
      recoveryDirectory: 'unused',
      log: vi.fn(),
      prepare: vi.fn(),
      teardown: vi.fn(),
      restore: vi.fn(),
      emitProgress: vi.fn()
    })
  ).rejects.toThrow('invalid Meu update authority')
})
