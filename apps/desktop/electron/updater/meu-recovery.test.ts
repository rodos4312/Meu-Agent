import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { expect, it } from 'vitest'

import { retainMeuInstaller } from './meu-recovery'
import type { MeuRelease } from './meu-release-feed'

it('retains verified installers across two updates and records the previous installed version for recovery', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'meu-recovery-'))
  try {
    const source = path.join(root, 'source.exe')
    const bytes = Buffer.from('nonexecutable retained recovery fixture')
    fs.writeFileSync(source, bytes)
    const release = (version: string): MeuRelease => ({
      schema: 1,
      repository: 'rodos4312/Meu-Agent',
      branch: 'dev/meu-foundation',
      channel: 'meu-preview',
      publisherName: 'CN=Meu Test Publisher',
      commit: 'a'.repeat(40),
      version,
      file: `Meu-${version}-win-x64.exe`,
      size: bytes.length,
      sha256: createHash('sha256').update(bytes).digest('hex'),
      sha512: createHash('sha512').update(bytes).digest('base64')
    })
    const cache = path.join(root, 'retained')
    const first = release('0.1.0-dev.8'),
      second = release('0.1.0-dev.9')
    await retainMeuInstaller(cache, source, first, '0.1.0-dev.7')
    await retainMeuInstaller(cache, source, second, first.version)
    const journal = JSON.parse(fs.readFileSync(path.join(cache, 'meu-update-recovery.json'), 'utf8'))
    expect(journal.rollback).toEqual(first)
    expect(journal.target).toEqual(second)
    expect(fs.readFileSync(path.join(cache, first.file))).toEqual(bytes)
    expect(fs.readFileSync(path.join(cache, second.file))).toEqual(bytes)
    fs.writeFileSync(source, 'tampered')
    await expect(retainMeuInstaller(cache, source, release('0.1.0-dev.10'), second.version)).rejects.toThrow('mismatch')
    expect(JSON.parse(fs.readFileSync(path.join(cache, 'meu-update-recovery.json'), 'utf8'))).toEqual(journal)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})
