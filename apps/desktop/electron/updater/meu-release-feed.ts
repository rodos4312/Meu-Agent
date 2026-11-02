import { gt, valid } from 'semver'

import releasePolicy from '../../meu-release.cjs'

export interface MeuRelease {
  schema: 1
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
}

interface GitHubRelease {
  draft: boolean
  tag_name: string
  assets: Array<{ name: string; browser_download_url: string; size: number }>
}

export function meuReleaseDirectory(version: string): string {
  if (!valid(version)) throw new Error('Invalid Meu release version.')
  return `https://github.com/${releasePolicy.REPOSITORY}/releases/download/meu-v${version}/`
}

export function validateMeuRelease(value: unknown, version: string, publisher: string): MeuRelease {
  const r = value as MeuRelease
  if (
    !r ||
    r.schema !== 1 ||
    r.repository !== releasePolicy.REPOSITORY ||
    r.branch !== releasePolicy.BRANCH ||
    r.channel !== releasePolicy.CHANNEL ||
    r.version !== version ||
    r.publisherName !== publisher ||
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
  return r
}

/** Public release metadata only: no user identifiers, API keys or chat data. */
export async function fetchMeuJson(url: string): Promise<unknown> {
  const allowed = `https://api.github.com/repos/${releasePolicy.REPOSITORY}/releases`
  const assetPrefix = `https://github.com/${releasePolicy.REPOSITORY}/releases/download/meu-v`
  if (!url.startsWith(allowed) && !url.startsWith(assetPrefix)) throw new Error('Foreign Meu update origin.')
  const response = await fetchMeuResponse(url)
  if (!response.ok || !response.body) throw new Error(`Meu release lookup failed (${response.status}).`)
  const chunks: Uint8Array[] = []
  let size = 0
  for await (const chunk of response.body) {
    size += chunk.length
    if (size > 2 * 1024 * 1024) throw new Error('Meu release metadata exceeds its size limit.')
    chunks.push(chunk)
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'))
}

async function fetchMeuResponse(url: string): Promise<Response> {
  const signal = AbortSignal.timeout(30_000)
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const response = await fetch(url, { signal, redirect: 'manual', headers: { Accept: 'application/json' } })
    if (![301, 302, 303, 307, 308].includes(response.status)) return response
    const location = response.headers.get('location')
    if (!location) throw new Error('Missing Meu release redirect.')
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
  if (!valid(current)) throw new Error('Current Meu version is invalid.')
  const response = await readJson(`https://api.github.com/repos/${releasePolicy.REPOSITORY}/releases?per_page=50`)
  if (!Array.isArray(response)) throw new Error('Invalid GitHub releases response.')
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
  if (!candidates.length) return null
  const release = candidates[0]
  const version = release.tag_name.slice(5)
  const directory = meuReleaseDirectory(version)
  for (const name of ['meu-release.json', 'meu-preview.yml', `Meu-${version}-win-x64.exe`]) {
    const assets = release.assets.filter(asset => asset.name === name)
    if (assets.length !== 1 || assets[0].browser_download_url !== directory + name)
      throw new Error('Meu release assets are missing or use a foreign origin.')
  }
  const manifest = validateMeuRelease(await readJson(directory + 'meu-release.json'), version, publisher)
  if (release.assets.find(a => a.name === manifest.file)?.size !== manifest.size)
    throw new Error('Meu release asset size differs from its manifest.')
  return manifest
}
