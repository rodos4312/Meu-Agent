import { describe, expect, it, vi } from 'vitest'

import {
  fetchMeuJson,
  findMeuRelease,
  meuReleaseDirectory,
  validateMeuRelease,
  type MeuRelease
} from './meu-release-feed'

export const releaseFixture = (version = '0.1.0-dev.8'): MeuRelease => ({
  schema: 1,
  repository: 'rodos4312/Meu-Agent',
  branch: 'dev/meu-foundation',
  channel: 'meu-preview',
  version,
  commit: 'a'.repeat(40),
  publisherName: 'CN=Meu Test Publisher',
  file: `Meu-${version}-win-x64.exe`,
  size: 12,
  sha256: 'b'.repeat(64),
  sha512: Buffer.alloc(64).toString('base64')
})

function githubRelease(r: MeuRelease, draft = false) {
  return {
    draft,
    tag_name: `meu-v${r.version}`,
    assets: ['meu-release.json', 'meu-preview.yml', r.file].map(name => ({
      name,
      browser_download_url: meuReleaseDirectory(r.version) + name,
      size: r.size
    }))
  }
}

describe('Meu release authority', () => {
  it('selects a newer Meu release while ignoring drafts, old versions and upstream tags', async () => {
    const r = releaseFixture()
    const releases = [
      githubRelease(releaseFixture('0.1.0-dev.9'), true),
      githubRelease(releaseFixture('0.1.0-dev.5')),
      { ...githubRelease(r), tag_name: 'v99.0.0' },
      githubRelease(r)
    ]
    const read = vi.fn(async (url: string) => (url.includes('api.github.com') ? releases : r))
    await expect(findMeuRelease('0.1.0-dev.7', r.publisherName, read)).resolves.toEqual(r)
    expect(read.mock.calls[1][0]).toBe(meuReleaseDirectory(r.version) + 'meu-release.json')
  })

  it.each(['repository', 'branch', 'publisherName', 'commit', 'sha256', 'sha512', 'file'] as const)(
    'rejects altered %s metadata',
    field => {
      const r = releaseFixture()
      expect(() => validateMeuRelease({ ...r, [field]: 'foreign' }, r.version, r.publisherName)).toThrow()
    }
  )

  it('refuses foreign asset URLs before fetching their metadata', async () => {
    const r = releaseFixture()
    const gh = githubRelease(r)
    gh.assets[0].browser_download_url = 'https://example.com/meu-release.json'
    const read = vi.fn(async () => [gh])
    await expect(findMeuRelease('0.1.0-dev.7', r.publisherName, read)).rejects.toThrow('foreign origin')
    expect(read).toHaveBeenCalledTimes(1)
  })

  it('returns no update for the same version without contacting any download origin', async () => {
    const r = releaseFixture()
    const read = vi.fn(async () => [githubRelease(r)])
    await expect(findMeuRelease(r.version, r.publisherName, read)).resolves.toBeNull()
    expect(read).toHaveBeenCalledTimes(1)
  })

  it('rejects metadata redirects outside GitHub infrastructure', async () => {
    const fetchMock = vi.fn(
      async () => new Response(null, { status: 302, headers: { location: 'https://example.com/file' } })
    )
    vi.stubGlobal('fetch', fetchMock)
    try {
      await expect(fetchMeuJson(meuReleaseDirectory('0.1.0-dev.8') + 'meu-release.json')).rejects.toThrow(
        'leaves GitHub'
      )
      expect(fetchMock).toHaveBeenCalledTimes(1)
    } finally {
      vi.unstubAllGlobals()
    }
  })
})
