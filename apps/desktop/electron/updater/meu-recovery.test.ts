import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createHash, generateKeyPairSync } from 'node:crypto'
import { expect, it } from 'vitest'

import { retainMeuInstaller } from './meu-recovery'
import type { MeuRelease } from './meu-release-feed'
import signing from '../../meu-release-signing.cjs'

it.each(['authenticode', 'ed25519'])(
  'retains verified installers and previous-version recovery with %s authority',
  async mode => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'meu-recovery-'))
    try {
      const source = path.join(root, 'source.exe')
      const bytes = Buffer.from('nonexecutable retained recovery fixture')
      fs.writeFileSync(source, bytes)
      const keys = generateKeyPairSync('ed25519')
      const authority =
        mode === 'ed25519'
          ? keys.publicKey.export({ format: 'der', type: 'spki' }).toString('base64')
          : 'CN=Meu Test Publisher'
      const release = (version: string): MeuRelease => {
        const metadata: MeuRelease = {
          schema: mode === 'ed25519' ? 2 : 1,
          repository: 'rodos4312/Meu-Agent',
          branch: 'dev/meu-foundation',
          channel: 'meu-preview',
          publisherName: mode === 'ed25519' ? '' : authority,
          commit: 'a'.repeat(40),
          version,
          file: `Meu-${version}-win-x64.exe`,
          size: bytes.length,
          sha256: createHash('sha256').update(bytes).digest('hex'),
          sha512: createHash('sha512').update(bytes).digest('base64')
        }
        return mode === 'ed25519' ? signing.signRelease(metadata, keys.privateKey, authority) : metadata
      }
      const cache = path.join(root, 'retained')
      const first = release('0.1.0-dev.8'),
        second = release('0.1.0-dev.9')
      await retainMeuInstaller(cache, source, first, '0.1.0-dev.7', authority)
      await retainMeuInstaller(cache, source, second, first.version, authority)
      const journal = JSON.parse(fs.readFileSync(path.join(cache, 'meu-update-recovery.json'), 'utf8'))
      expect(journal.rollback).toEqual(first)
      expect(journal.target).toEqual(second)
      expect(fs.readFileSync(path.join(cache, first.file))).toEqual(bytes)
      expect(fs.readFileSync(path.join(cache, second.file))).toEqual(bytes)
      fs.writeFileSync(source, 'tampered')
      await expect(
        retainMeuInstaller(cache, source, release('0.1.0-dev.10'), second.version, authority)
      ).rejects.toThrow('mismatch')
      expect(JSON.parse(fs.readFileSync(path.join(cache, 'meu-update-recovery.json'), 'utf8'))).toEqual(journal)
    } finally {
      fs.rmSync(root, { recursive: true, force: true })
    }
  }
)
