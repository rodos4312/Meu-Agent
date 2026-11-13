import { describe, expect, it, vi } from 'vitest'

import releasePolicy from '../../meu-release.cjs'
import { buildStampPayload } from '../../scripts/write-build-stamp.mjs'

import {
  isMeuChannelVersion,
  meuChannelOf,
  meuChannelPreference,
  meuChannelSpec,
  meuRcReleasesUrl,
  meuTransition,
  STABLE_CHANNEL
} from './meu-channel'
import { fetchMeuJson, findMeuRelease, type MeuRelease, meuReleaseDirectory, validateMeuRelease } from './meu-release-feed'
import { releaseFixture } from './meu-release-feed.test'

const RC = meuChannelSpec('rc')

const rcFixture = (version = '0.1.0-rc.1'): MeuRelease => ({
  ...releaseFixture(version),
  repository: RC.repository,
  branch: 'rc/meu-vnext-rc1',
  channel: RC.channel
})

function listed(r: MeuRelease, spec = STABLE_CHANNEL) {
  return {
    draft: false,
    tag_name: `${spec.tagPrefix}${r.version}`,
    assets: ['meu-release.json', `${spec.channel}.yml`, r.file].map(name => ({
      name,
      browser_download_url: meuReleaseDirectory(r.version, spec) + name,
      size: r.size
    }))
  }
}

function feed(releases: MeuRelease[], spec = STABLE_CHANNEL) {
  const byDirectory = new Map(releases.map(r => [meuReleaseDirectory(r.version, spec) + 'meu-release.json', r]))
  return vi.fn(async (url: string) => (url.includes('api.github.com') ? releases.map(r => listed(r, spec)) : byDirectory.get(url)))
}

describe('Meu update channel preference and migration', () => {
  it('an existing install without a saved channel stays on stable', () => {
    expect(meuChannelPreference(undefined, 'stable')).toBe('stable')
    expect(meuChannelPreference(JSON.parse('{"branch":"main"}').channel, 'stable')).toBe('stable')
  })

  it.each([null, '', 'canary', 'RC', 7, {}])('an unknown saved value %j never moves a stable install to RC', value => {
    expect(meuChannelPreference(value, 'stable')).toBe('stable')
  })

  it('an RC build defaults to RC and a saved preference wins', () => {
    expect(meuChannelPreference(undefined, 'rc')).toBe('rc')
    expect(meuChannelPreference('stable', 'rc')).toBe('stable')
    expect(meuChannelPreference('rc', 'stable')).toBe('rc')
  })

  it('names the RC release page only for an RC preference, without credentials', () => {
    expect(meuRcReleasesUrl('stable')).toBeNull()
    const url = new URL(meuRcReleasesUrl('rc')!)
    expect(url.href).toBe('https://github.com/rodos4312/Meu-Agent-RC-private/releases')
    expect(url.username + url.password + url.search).toBe('')
  })
})

describe('Meu version rules', () => {
  it.each([
    ['0.1.0-dev.34', 'stable', true],
    ['0.1.0', 'stable', true],
    ['0.1.0-rc.1', 'rc', true],
    ['0.1.0-rc.1', 'stable', false],
    ['0.1.0-dev.34', 'rc', false],
    ['0.1.0-dev.34-rc1', 'rc', false],
    ['0.1.0-rc1', 'rc', false],
    ['v0.1.0', 'stable', false],
    ['0.1.0-dev.x', 'stable', false],
    ['0.1', 'stable', false]
  ] as const)('%s is %s grammar: %s', (version, channel, ok) => {
    expect(isMeuChannelVersion(version, meuChannelSpec(channel))).toBe(ok)
  })

  it.each([
    ['rc', '0.1.0-rc.1', 'rc', '0.1.0-rc.2', true, undefined],
    ['rc', '0.1.0-rc.2', 'rc', '0.1.0-rc.1', false, 'not-newer'],
    ['rc', '0.1.0-rc.1', 'stable', '0.1.0', true, undefined],
    ['rc', '0.1.0-rc.1', 'stable', '0.1.0-dev.40', false, 'not-newer'],
    ['stable', '0.1.0-dev.34', 'stable', '0.1.0-dev.35', true, undefined],
    ['stable', '0.1.0-dev.35', 'stable', '0.1.0-dev.34', false, 'not-newer'],
    ['stable', '0.1.0-dev.34', 'stable', '0.1.0-dev.34', false, 'not-newer'],
    ['stable', '0.1.0-dev.34', 'rc', '0.1.0-rc.1', false, 'rc-on-stable'],
    ['stable', '0.1.0-dev.34', 'stable', '0.1.0-dev.35-rc1', false, 'malformed-version'],
    ['rc', 'garbage', 'rc', '0.1.0-rc.2', false, 'malformed-version']
  ] as const)('%s %s -> %s %s', (fromChannel, from, toChannel, to, allowed, reason) => {
    const result = meuTransition({ channel: fromChannel, version: from }, { channel: toChannel, version: to })
    expect(result.allowed).toBe(allowed)
    expect('reason' in result ? result.reason : undefined).toBe(reason)
  })
})

describe('Meu feeds per channel', () => {
  it('stable sees the newest stable update', async () => {
    const read = feed([releaseFixture('0.1.0-dev.9'), releaseFixture('0.1.0-dev.10')])
    await expect(findMeuRelease('0.1.0-dev.8', 'CN=Meu Test Publisher', read)).resolves.toMatchObject({
      version: '0.1.0-dev.10'
    })
  })

  it('stable ignores RC tags and RC versions published under stable tags', async () => {
    const rcUnderStableTag = { ...listed(releaseFixture('0.1.0-dev.9')), tag_name: 'meu-v0.1.0-rc.1' }
    const read = vi.fn(async () => [listed(rcFixture(), RC), rcUnderStableTag])
    await expect(findMeuRelease('0.1.0-dev.8', 'CN=Meu Test Publisher', read)).resolves.toBeNull()
    expect(read).toHaveBeenCalledOnce()
  })

  it('rejects RC channel metadata served from the stable feed (wrong channel)', async () => {
    const stable = releaseFixture('0.1.0-dev.9')
    const read = vi.fn(async (url: string) =>
      url.includes('api.github.com') ? [listed(stable)] : { ...stable, channel: RC.channel }
    )
    await expect(findMeuRelease('0.1.0-dev.8', 'CN=Meu Test Publisher', read)).rejects.toThrow('another publisher')
  })

  it('RC sees a newer RC through an explicitly provided reader only', async () => {
    const read = feed([rcFixture('0.1.0-rc.1'), rcFixture('0.1.0-rc.2')], RC)
    await expect(findMeuRelease('0.1.0-rc.1', 'CN=Meu Test Publisher', read, RC, 'rc')).resolves.toMatchObject({
      version: '0.1.0-rc.2',
      channel: 'meu-rc'
    })
  })

  it('an RC build moves only to a strictly newer stable release', async () => {
    const read = feed([releaseFixture('0.1.0-dev.40'), releaseFixture('0.1.0')])
    await expect(findMeuRelease('0.1.0-rc.1', 'CN=Meu Test Publisher', read, STABLE_CHANNEL, 'rc')).resolves.toMatchObject({
      version: '0.1.0'
    })
    const older = feed([releaseFixture('0.1.0-dev.40')])
    await expect(findMeuRelease('0.1.0-rc.1', 'CN=Meu Test Publisher', older, STABLE_CHANNEL, 'rc')).resolves.toBeNull()
  })

  it('refuses a malformed installed version instead of guessing', async () => {
    await expect(findMeuRelease('0.1.0-rc.1', 'CN=Meu Test Publisher', vi.fn())).rejects.toThrow('invalid')
  })

  it.each([
    ['foreign repository', { repository: 'someone/Meu-Agent' }],
    ['RC repository with stable channel', { repository: RC.repository }],
    ['foreign branch', { branch: 'main' }]
  ])('wrong source is blocked: %s', (_name, change) => {
    const r = releaseFixture('0.1.0-dev.9')
    expect(() => validateMeuRelease({ ...r, ...change }, r.version, r.publisherName)).toThrow()
  })

  it('a manifest is valid only for its own channel', () => {
    const rc = rcFixture()
    expect(validateMeuRelease(rc, rc.version, rc.publisherName, RC)).toEqual(rc)
    // Rollback and recovery validate with the stable channel: an RC can never become a stable rollback target.
    expect(() => validateMeuRelease(rc, rc.version, rc.publisherName)).toThrow()
    const stable = releaseFixture('0.1.0-dev.9')
    expect(() => validateMeuRelease(stable, stable.version, stable.publisherName, RC)).toThrow()
  })

  it('never fetches the private RC repository, so no credential is ever needed or sent', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    try {
      await expect(fetchMeuJson(`https://api.github.com/repos/${RC.repository}/releases`, RC)).rejects.toThrow('manually')
      expect(fetchMock).not.toHaveBeenCalled()
    } finally {
      vi.unstubAllGlobals()
    }
  })
})

describe('Meu build stamps per channel', () => {
  const stamp = (branch: string) => ({ commit: 'c'.repeat(40), branch, builtAt: '', dirty: false, source: 'ci' })

  it('a default build is stable and keeps the historic stable identity', () => {
    const built = buildStampPayload(stamp('dev/meu-foundation'), {}, 'win32')
    expect(meuChannelOf(built.meuUpdates)?.id).toBe('stable')
    expect(built.meuUpdates).toMatchObject({ repository: 'rodos4312/Meu-Agent', channel: 'meu-preview' })
  })

  it('an RC build carries the RC identity and its own rc/* branch', () => {
    const built = buildStampPayload(stamp('rc/meu-vnext-rc1'), { MEU_UPDATE_CHANNEL: 'rc' }, 'win32')
    expect(meuChannelOf(built.meuUpdates)?.id).toBe('rc')
    expect(built.meuUpdates).toMatchObject({ repository: RC.repository, branch: 'rc/meu-vnext-rc1', channel: 'meu-rc' })
  })

  it.each([
    [{}, 'rc/meu-vnext-rc1'],
    [{ MEU_UPDATE_CHANNEL: 'rc' }, 'dev/meu-foundation'],
    [{ MEU_UPDATE_CHANNEL: 'rc' }, 'main']
  ])('refuses a build whose branch is not admitted by its channel (%j on %s)', (env, branch) => {
    expect(() => buildStampPayload(stamp(branch), env, 'win32')).toThrow('admitted')
  })

  it('a release-request tag admits only a stable build, never an RC', () => {
    const env = { GITHUB_REPOSITORY: RC.repository, GITHUB_SHA: 'c'.repeat(40), GITHUB_REF_NAME: 'meu-release-request-0.1.0-rc.1' }
    expect(() => buildStampPayload(stamp('meu-release-request-0.1.0-rc.1'), { ...env, MEU_UPDATE_CHANNEL: 'rc' }, 'win32')).toThrow('admitted')
    const stable = { ...env, GITHUB_REPOSITORY: 'rodos4312/Meu-Agent', GITHUB_REF_NAME: 'meu-release-request-0.1.0-dev.35' }
    expect(buildStampPayload(stamp('meu-release-request-0.1.0-dev.35'), stable, 'win32').meuUpdates.branch).toBe('dev/meu-foundation')
  })

  it('refuses an unknown build channel', () => {
    expect(() => releasePolicy.buildUpdateChannel({ MEU_UPDATE_CHANNEL: 'beta' })).toThrow('Unknown')
  })

  it('serializes no credential from the build environment into the stamp', () => {
    const env = { MEU_UPDATE_CHANNEL: 'rc', GITHUB_TOKEN: 'ghp_' + 'x'.repeat(36), MEU_RELEASE_PRIVATE_KEY: 'secret-key' }
    const text = JSON.stringify(buildStampPayload(stamp('rc/meu-vnext-rc1'), env, 'win32'))
    expect(text).not.toContain('ghp_')
    expect(text).not.toContain('secret-key')
    expect(Object.keys(releasePolicy.meuReleasePolicy(env, 'rc/x')).sort()).toEqual(['branch', 'channel', 'publicKey', 'repository'])
  })
})
