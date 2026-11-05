import { gt, valid } from 'semver'

import signing from '../../meu-release-signing.cjs'
import releasePolicy from '../../meu-release.cjs'

export interface MeuRelease {
  schema: 1 | 2
  repository: string
  branch: string
  channel: string
  version: string
  commit: string
  publisherName: string
  file: string
  size: number
  sha256: string
  sha512: string
  signature?: string
}

interface GitHubRelease {
  draft: boolean
  tag_name: string
  assets: Array<{ name: string; browser_download_url: string; size: number }>
}

class MeuReleaseLookupError extends Error {
  constructor(readonly status: number) {
    super(`Meu release lookup failed (${status}).`)
  }
}

export function meuReleaseDirectory(version: string): string {
  if (!valid(version)) {
    throw new Error('Invalid Meu release version.')
  }

  return `https://github.com/${releasePolicy.REPOSITORY}/releases/download/meu-v${version}/`
}

export function validateMeuRelease(value: unknown, version: string, publisher: string): MeuRelease {
  const r = value as MeuRelease

  if (
    !r ||
    ![1, 2].includes(r.schema) ||
    r.repository !== releasePolicy.REPOSITORY ||
    r.branch !== releasePolicy.BRANCH ||
    r.channel !== releasePolicy.CHANNEL ||
    r.version !== version ||
    (publisher.startsWith('CN=')
      ? r.schema !== 1 || r.publisherName !== publisher
      : r.schema !== 2 || r.publisherName !== '') ||
    !/^[a-f0-9]{40}$/.test(r.commit) ||
    r.file !== `Meu-${version}-win-x64.exe` ||
    !Number.isSafeInteger(r.size) ||
    r.size < 1 ||
    r.size > 512 * 1024 * 1024 ||
    !/^[a-f0-9]{64}$/.test(r.sha256) ||
    !/^[A-Za-z0-9+/]{86}==$/.test(r.sha512)
  ) {
    throw new Error('Meu release metadata is invalid or belongs to another publisher, repository or branch.')
  }

  if (!publisher.startsWith('CN=')) {
    signing.verifyRelease(r, publisher)
  }

  return r
}

/** Public release metadata only: no user identifiers, API keys or chat data. */
export async function fetchMeuJson(url: string): Promise<unknown> {
  const allowed = `https://api.github.com/repos/${releasePolicy.REPOSITORY}/releases`
  const assetPrefix = `https://github.com/${releasePolicy.REPOSITORY}/releases/download/meu-v`

  if (!url.startsWith(allowed) && !url.startsWith(assetPrefix)) {
    throw new Error('Foreign Meu update origin.')
  }

  const response = await fetchMeuResponse(url)

  if (!response.ok) {
    throw new MeuReleaseLookupError(response.status)
  }

  if (!response.body) {
    throw new Error('Meu release metadata is empty.')
  }

  const chunks: Uint8Array[] = []
  let size = 0

  for await (const chunk of response.body) {
    size += chunk.length

    if (size > 2 * 1024 * 1024) {
      throw new Error('Meu release metadata exceeds its size limit.')
    }

    chunks.push(chunk)
  }

  return JSON.parse(Buffer.concat(chunks).toString('utf8'))
}

export async function fetchMeuResponse(url: string, timeoutMs = 30_000): Promise<Response> {
  const signal = AbortSignal.timeout(timeoutMs)

  for (let attempt = 0; attempt < 4; attempt += 1) {
    const response = await fetch(url, { signal, redirect: 'manual', headers: { Accept: 'application/json' } })

    if (![301, 302, 303, 307, 308].includes(response.status)) {
      return response
    }

    const location = response.headers.get('location')

    if (!location) {
      throw new Error('Missing Meu release redirect.')
    }

    const target = new URL(location, url)

    if (
      target.protocol !== 'https:' ||
      target.username ||
      target.password ||
      !['github.com', 'release-assets.githubusercontent.com'].includes(target.hostname)
    ) {
      throw new Error('Meu release redirect leaves GitHub download infrastructure.')
    }

    url = target.href
  }

  throw new Error('Too many Meu release redirects.')
}

export async function findMeuRelease(
  current: string,
  publisher: string,
  readJson: (url: string) => Promise<unknown> = fetchMeuJson
): Promise<MeuRelease | null> {
  if (!valid(current)) {
    throw new Error('Current Meu version is invalid.')
  }

  const response = await readJson(`https://api.github.com/repos/${releasePolicy.REPOSITORY}/releases?per_page=50`)

  if (!Array.isArray(response)) {
    throw new Error('Invalid GitHub releases response.')
  }

  const candidates = (response as GitHubRelease[])
    .filter(
      r =>
        !r.draft &&
        typeof r.tag_name === 'string' &&
        r.tag_name.startsWith('meu-v') &&
        valid(r.tag_name.slice(5)) &&
        gt(r.tag_name.slice(5), current)
    )
    .sort((a, b) => (gt(a.tag_name.slice(5), b.tag_name.slice(5)) ? -1 : 1))

  if (!candidates.length) {
    return null
  }

  return verifyPublishedMeuRelease(candidates[0], publisher, readJson)
}

async function verifyPublishedMeuRelease(
  release: GitHubRelease,
  publisher: string,
  readJson: (url: string) => Promise<unknown>
): Promise<MeuRelease> {
  const version = release.tag_name.slice(5)
  const directory = meuReleaseDirectory(version)

  for (const name of ['meu-release.json', 'meu-preview.yml', `Meu-${version}-win-x64.exe`]) {
    const assets = release.assets.filter(asset => asset.name === name)

    if (assets.length !== 1 || assets[0].browser_download_url !== directory + name) {
      throw new Error('Meu release assets are missing or use a foreign origin.')
    }
  }

  const manifest = validateMeuRelease(await readJson(directory + 'meu-release.json'), version, publisher)

  if (release.assets.find(a => a.name === manifest.file)?.size !== manifest.size) {
    throw new Error('Meu release asset size differs from its manifest.')
  }

  return manifest
}

/** The installed version is a recovery pin, never a request for a newer release. */
export async function readMeuRelease(
  version: string,
  publisher: string,
  readJson: (url: string) => Promise<unknown> = fetchMeuJson
): Promise<MeuRelease> {
  meuReleaseDirectory(version)
  let response: unknown

  try {
    response = await readJson(`https://api.github.com/repos/${releasePolicy.REPOSITORY}/releases/tags/meu-v${version}`)
  } catch (error) {
    if (error instanceof MeuReleaseLookupError && error.status === 404) {
      throw new Error(
        `This installed Meu release is no longer available for automatic recovery. Download and run the latest Meu installer from https://github.com/${releasePolicy.REPOSITORY}/releases.`
      )
    }

    throw error
  }

  const release = response as GitHubRelease

  if (!release || release.draft || release.tag_name !== `meu-v${version}` || !Array.isArray(release.assets)) {
    throw new Error('The installed Meu release is unavailable as a verified recovery version.')
  }

  return verifyPublishedMeuRelease(release, publisher, readJson)
}
