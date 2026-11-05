import assert from 'node:assert/strict'
import { createWriteStream } from 'node:fs'
import { copyFile, mkdir, mkdtemp, rm, rmdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { pipeline } from 'node:stream/promises'
import { pathToFileURL } from 'node:url'
import { lt, rcompare, valid } from 'semver'

import policy from '../meu-release.cjs'
import signing from '../meu-release-signing.cjs'
import trust from '../meu-update-key.json' with { type: 'json' }
import { verifiedMeuCandidate } from './meu-upgrade-transport.mjs'

export const RETAINED_MEU_RELEASES = 3 // Current release plus two previous releases; never an age cutoff.
const apiRoot = `https://api.github.com/repos/${policy.REPOSITORY}/`
const assetRoot = `https://github.com/${policy.REPOSITORY}/releases/download/`

function versionOf(release) {
  if (release.draft || typeof release.tag_name !== 'string' || !release.tag_name.startsWith('meu-v')) return null
  const version = release.tag_name.slice(5)
  return valid(version) === version ? version : null
}

export function orderedMeuReleases(releases) {
  assert(Array.isArray(releases), 'Invalid release inventory')
  const ordered = releases.filter(release => versionOf(release)).sort((a, b) => rcompare(versionOf(a), versionOf(b)))
  const ids = new Set(),
    versions = new Set()
  for (const release of ordered) {
    assert(Number.isSafeInteger(release.id) && release.id > 0, 'Invalid release ID')
    assert(!ids.has(release.id) && !versions.has(versionOf(release)), 'Duplicate release inventory')
    ids.add(release.id)
    versions.add(versionOf(release))
  }
  return ordered
}

export async function githubApi(endpoint, method = 'GET') {
  assert(/^releases(?:\?per_page=100&page=\d+|\/\d+)?$/.test(endpoint), 'Unexpected release API operation')
  assert(['GET', 'DELETE'].includes(method), 'Unexpected release API method')
  const response = await fetch(apiRoot + endpoint, {
    method,
    redirect: 'error',
    signal: AbortSignal.timeout(30_000),
    headers: {
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      ...(process.env.GH_TOKEN ? { Authorization: `Bearer ${process.env.GH_TOKEN}` } : {})
    }
  })
  assert(response.ok, `GitHub release API failed (${response.status})`)
  return response.status === 204 ? null : response.json()
}

export async function fetchPublicArtifact(url, timeoutMs = 600_000) {
  assert(url.startsWith(assetRoot), 'Foreign release artifact origin')
  const signal = AbortSignal.timeout(timeoutMs)
  for (let redirects = 0; redirects < 5; redirects++) {
    const response = await fetch(url, { redirect: 'manual', signal })
    if (![301, 302, 303, 307, 308].includes(response.status)) {
      assert(response.ok && response.body, `Public artifact download failed (${response.status})`)
      return response
    }
    const location = response.headers.get('location')
    assert(location, 'Missing artifact redirect')
    const target = new URL(location, url)
    assert(
      target.protocol === 'https:' &&
        !target.username &&
        !target.password &&
        ['github.com', 'release-assets.githubusercontent.com'].includes(target.hostname),
      'Foreign artifact redirect'
    )
    url = target.href
  }
  throw new Error('Too many artifact redirects')
}

async function readManifest(url) {
  const response = await fetchPublicArtifact(url, 30_000)
  const chunks = []
  let size = 0
  for await (const chunk of response.body) {
    size += chunk.length
    assert(size <= 2 * 1024 * 1024, 'Release manifest exceeds its size limit')
    chunks.push(chunk)
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'))
}

export async function readMeuReleaseCatalog(api = githubApi) {
  const releases = []
  for (let page = 1; page <= 20; page++) {
    const entries = await api(`releases?per_page=100&page=${page}`)
    assert(Array.isArray(entries), 'Invalid release inventory page')
    releases.push(...entries)
    if (entries.length < 100) return orderedMeuReleases(releases)
  }
  throw new Error('Release inventory exceeds the supported maintenance bound; nothing removed')
}

export async function verifyPublishedMeuRelease(entry, source = {}) {
  const version = versionOf(entry)
  assert(version, 'Expected a published Meu release')
  const base = assetRoot + entry.tag_name + '/'
  const file = `Meu-${version}-win-x64.exe`
  for (const name of ['meu-release.json', 'meu-preview.yml', file]) {
    const matches = entry.assets.filter(asset => asset.name === name)
    assert(matches.length === 1 && matches[0].browser_download_url === base + name, 'Missing or foreign release asset')
  }
  const release = await (source.readManifest ?? readManifest)(base + 'meu-release.json')
  signing.verifyRelease(release, source.publicKey ?? trust.publicKey)
  assert(
    release.repository === policy.REPOSITORY &&
      release.branch === policy.BRANCH &&
      release.channel === policy.CHANNEL &&
      release.version === version &&
      release.file === file &&
      /^[a-f0-9]{40}$/.test(release.commit) &&
      Number.isSafeInteger(release.size) &&
      /^[a-f0-9]{64}$/.test(release.sha256) &&
      /^[A-Za-z0-9+/]{86}==$/.test(release.sha512) &&
      release.size > 0 &&
      release.size <= 512 * 1024 * 1024,
    'Invalid signed release policy'
  )
  const installer = entry.assets.find(asset => asset.name === file)
  assert(
    installer.size === release.size && installer.digest === `sha256:${release.sha256}`,
    'Installer differs from signed manifest'
  )
  return release
}

export async function pruneMeuReleases({ apply = false, api = githubApi, ...source } = {}) {
  const ordered = await readMeuReleaseCatalog(api)
  const retained = ordered.slice(0, RETAINED_MEU_RELEASES)
  // An incomplete or forged new publication must never evict a known working installer.
  for (const entry of retained) await verifyPublishedMeuRelease(entry, source)
  const retired = ordered.slice(RETAINED_MEU_RELEASES)
  const removed = []
  if (apply) {
    for (const entry of retired) {
      const current = await api(`releases/${entry.id}`)
      assert(
        current.id === entry.id && current.tag_name === entry.tag_name && !current.draft,
        'Release changed before deletion; maintenance stopped'
      )
      await api(`releases/${entry.id}`, 'DELETE') // Release assets only; never delete Git tags or commits.
      removed.push(entry.tag_name)
    }
  }
  return {
    retained: retained.map(entry => entry.tag_name),
    retire: retired.map(entry => entry.tag_name),
    removed,
    dryRun: !apply
  }
}

export async function downloadMeuBaseline(
  version,
  directory,
  { api = githubApi, fetchArtifact = fetchPublicArtifact, ...source } = {}
) {
  assert(valid(version) === version && path.isAbsolute(directory), 'Invalid baseline request')
  const catalog = await readMeuReleaseCatalog(api)
  const entry = catalog.find(release => lt(versionOf(release), version))
  assert(entry, 'No previous published Meu release is available for the upgrade rehearsal')
  const release = await verifyPublishedMeuRelease(entry, source)
  const parent = path.dirname(directory)
  await mkdir(parent, { recursive: true })
  const temporary = await mkdtemp(path.join(parent, '.meu-baseline-'))
  const installer = path.join(temporary, release.file)
  const manifest = path.join(temporary, 'meu-release.json')
  try {
    const response = await fetchArtifact(assetRoot + entry.tag_name + '/' + release.file)
    assert(response.ok && response.body, 'Baseline download failed')
    let size = 0
    await pipeline(
      response.body,
      async function* (chunks) {
        for await (const chunk of chunks) {
          size += chunk.length
          assert(size <= release.size, 'Baseline exceeds its signed size')
          yield chunk
        }
      },
      createWriteStream(installer)
    )
    await writeFile(manifest, JSON.stringify(release))
    verifiedMeuCandidate(temporary, source.publicKey ?? trust.publicKey)
    await mkdir(directory, { recursive: true })
    await copyFile(installer, path.join(directory, release.file))
    await copyFile(manifest, path.join(directory, 'meu-release.json'))
    return release
  } finally {
    // Only the two files in this freshly created, explicitly named temporary directory.
    await rm(installer, { force: true })
    await rm(manifest, { force: true })
    await rmdir(temporary)
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const [mode, ...args] = process.argv.slice(2)
  try {
    if (mode === 'prune') {
      assert(args.length === 0 || (args.length === 1 && args[0] === '--apply'), 'Unexpected retention arguments')
      const apply = args[0] === '--apply'
      if (apply)
        assert(
          process.env.GITHUB_ACTIONS === 'true' && process.env.GITHUB_REPOSITORY === policy.REPOSITORY,
          'Release removal is restricted to the Meu GitHub workflow'
        )
      console.log(JSON.stringify(await pruneMeuReleases({ apply }), null, 2))
    } else if (mode === 'baseline') {
      assert(args.length === 2, 'Expected candidate version and absolute baseline directory')
      const release = await downloadMeuBaseline(args[0], path.resolve(args[1]))
      console.log(`Verified public upgrade baseline: ${release.version} (${release.commit})`)
    } else {
      throw new Error('Expected prune [--apply] or baseline VERSION DIRECTORY')
    }
  } catch (error) {
    console.error(error.message)
    process.exitCode = 1
  }
}
