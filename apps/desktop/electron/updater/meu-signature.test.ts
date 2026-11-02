import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { expect, it } from 'vitest'

import { assertMeuSignature, verifyMeuSignature, type MeuSignature } from './meu-signature'

const file = path.resolve('Meu-installer.exe')
const good: MeuSignature = {
  status: 'Valid',
  kind: 'Authenticode',
  path: file,
  subject: 'CN=Meu Test Publisher',
  version: '0.1.0-dev.8'
}

it('accepts only the embedded signature of the exact expected file, publisher and version', () => {
  expect(() => assertMeuSignature(good, file, good.subject, good.version)).not.toThrow()
})

it.each([
  { status: 'NotSigned' },
  { status: 'HashMismatch' },
  { kind: 'Catalog' },
  { subject: 'CN=Someone Else' },
  { path: file + '.other' },
  { version: '0.1.0-dev.5' }
])('refuses invalid signature evidence %j', changed => {
  expect(() => assertMeuSignature({ ...good, ...changed }, file, good.subject, good.version)).toThrow()
})

it.skipIf(process.platform !== 'win32')(
  'native Windows verifier rejects unsigned bytes and treats shell characters in paths as data',
  async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'meu-signature-'))
    try {
      const target = path.join(root, "Meu-';Write-Output INJECTED;'.exe")
      fs.writeFileSync(target, 'unsigned security fixture; never executed')
      await expect(verifyMeuSignature(target, good.subject, good.version)).rejects.toThrow('signature')
    } finally {
      fs.rmSync(root, { recursive: true, force: true })
    }
  },
  40_000
)
