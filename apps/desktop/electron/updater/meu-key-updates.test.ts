import { createHash, generateKeyPairSync } from 'node:crypto'
import { expect, it, vi } from 'vitest'

import signing from '../../meu-release-signing.cjs'
import { findMeuRelease, meuReleaseDirectory, validateMeuRelease, type MeuRelease } from './meu-release-feed'

const keys = generateKeyPairSync('ed25519')
const publicKey = keys.publicKey.export({ format: 'der', type: 'spki' }).toString('base64')
const privateKey = keys.privateKey.export({ format: 'pem', type: 'pkcs8' })

function fixture(): MeuRelease {
  const bytes = Buffer.from('harmless installer fixture, never executed')
  return signing.signRelease(
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
    privateKey,
    publicKey
  )
}

it('accepts a release signed with the installed free key without any Windows certificate', async () => {
  const release = fixture()
  const directory = meuReleaseDirectory(release.version)
  const github = [
    {
      draft: false,
      tag_name: `meu-v${release.version}`,
      assets: ['meu-release.json', 'meu-preview.yml', release.file].map(name => ({
        name,
        size: release.size,
        browser_download_url: directory + name
      }))
    }
  ]
  const read = vi.fn(async (url: string) => (url.includes('api.github.com') ? github : release))
  await expect(findMeuRelease('0.1.0-dev.8', publicKey, read)).resolves.toEqual(release)
  expect(read.mock.calls.flat().every(url => /github\.com/.test(url))).toBe(true)
})

it.each([
  'schema',
  'repository',
  'branch',
  'channel',
  'version',
  'commit',
  'publisherName',
  'file',
  'size',
  'sha256',
  'sha512',
  'signature'
])('rejects tampering with signed %s before offering an update', field => {
  const release = fixture()
  const changed = { ...release, [field]: field === 'size' ? release.size + 1 : 'tampered' }
  expect(() => validateMeuRelease(changed, release.version, publicKey)).toThrow()
})

it('rejects another valid key, unsigned metadata and attempts to fall back to Authenticode', () => {
  const release = fixture()
  const other = generateKeyPairSync('ed25519').publicKey.export({ format: 'der', type: 'spki' }).toString('base64')
  expect(() => validateMeuRelease(release, release.version, other)).toThrow()
  expect(() => validateMeuRelease({ ...release, signature: undefined }, release.version, publicKey)).toThrow()
  expect(() =>
    validateMeuRelease({ ...release, schema: 1, publisherName: 'CN=Other' }, release.version, publicKey)
  ).toThrow()
})
