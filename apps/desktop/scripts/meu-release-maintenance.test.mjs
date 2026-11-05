import assert from 'node:assert/strict'
import { createHash, generateKeyPairSync } from 'node:crypto'
import fs from 'node:fs'
import { createServer } from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { once } from 'node:events'
import { spawnSync } from 'node:child_process'
import { expect, test } from 'vitest'

import signing from '../meu-release-signing.cjs'
import { verifiedMeuCandidate } from './meu-upgrade-transport.mjs'
import {
  downloadMeuBaseline,
  orderedMeuReleases,
  pruneMeuReleases,
  readMeuReleaseCatalog
} from './meu-release-maintenance.mjs'

function fixture(versions) {
  const keys = generateKeyPairSync('ed25519')
  const publicKey = keys.publicKey.export({ format: 'der', type: 'spki' }).toString('base64')
  const bytes = Buffer.from('nonexecutable installer fixture')
  const manifests = new Map()
  const entries = versions.map((version, index) => {
    const manifest = signing.signRelease(
      {
        schema: 2,
        repository: 'rodos4312/Meu-Agent',
        branch: 'dev/meu-foundation',
        channel: 'meu-preview',
        version,
        commit: 'a'.repeat(40),
        publisherName: '',
        file: `Meu-${version}-win-x64.exe`,
        size: bytes.length,
        sha256: createHash('sha256').update(bytes).digest('hex'),
        sha512: createHash('sha512').update(bytes).digest('base64')
      },
      keys.privateKey,
      publicKey
    )
    manifests.set(`https://github.com/rodos4312/Meu-Agent/releases/download/meu-v${version}/meu-release.json`, manifest)
    return {
      id: index + 1,
      draft: false,
      tag_name: `meu-v${version}`,
      published_at: `2026-01-${index + 10}`,
      assets: ['meu-release.json', 'meu-preview.yml', manifest.file].map(name => ({
        name,
        size: bytes.length,
        digest: `sha256:${manifest.sha256}`,
        browser_download_url: `https://github.com/rodos4312/Meu-Agent/releases/download/meu-v${version}/${name}`
      }))
    }
  })
  return { entries, bytes, source: { publicKey, readManifest: async url => manifests.get(url) }, manifests }
}

// Actual HTTP inventory/readback/deletion, confined to an ephemeral loopback server.
async function serverFor(entries, run, changed = entry => entry) {
  const removed = []
  const server = createServer((req, res) => {
    if (req.url.startsWith('/releases?')) {
      res.setHeader('content-type', 'application/json')
      res.end(JSON.stringify(entries))
    } else {
      const entry = entries.find(item => req.url === `/releases/${item.id}`)
      if (!entry) {
        res.writeHead(404)
        res.end()
        return
      }
      if (req.method === 'DELETE') {
        removed.push(entry.tag_name)
        res.writeHead(204)
        res.end()
      } else {
        res.setHeader('content-type', 'application/json')
        res.end(JSON.stringify(changed(entry)))
      }
    }
  })
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  const base = `http://127.0.0.1:${server.address().port}/`
  const api = async (endpoint, method = 'GET') => {
    const response = await fetch(base + endpoint, { method })
    assert(response.ok)
    return response.status === 204 ? null : response.json()
  }
  try {
    await run({ api, removed })
  } finally {
    server.closeAllConnections()
    await new Promise(resolve => server.close(resolve))
  }
}

test('keeps current plus two previous semantic versions, regardless of age or publication order', async () => {
  const f = fixture(['0.1.0-dev.24', '0.1.0-dev.9', '0.1.0-dev.22', '0.1.0-dev.23', '0.1.0-dev.21'])
  const draft = { ...f.entries[0], id: 50, draft: true, tag_name: 'meu-v99.0.0' }
  const foreign = { ...f.entries[0], id: 51, tag_name: 'v100.0.0' }
  await serverFor([...f.entries, draft, foreign], async ({ api, removed }) => {
    const dry = await pruneMeuReleases({ ...f.source, api })
    expect(dry.retained).toEqual(['meu-v0.1.0-dev.24', 'meu-v0.1.0-dev.23', 'meu-v0.1.0-dev.22'])
    expect(dry.retire).toEqual(['meu-v0.1.0-dev.21', 'meu-v0.1.0-dev.9'])
    expect(removed).toEqual([])
    const applied = await pruneMeuReleases({ ...f.source, api, apply: true })
    expect(applied.removed).toEqual(dry.retire)
    expect(removed).toEqual(dry.retire)
  })
})

test('stable releases outrank their prereleases and duplicate inventories fail closed', () => {
  const f = fixture(['1.0.0-rc.1', '1.0.0', '0.9.0'])
  expect(orderedMeuReleases(f.entries).map(entry => entry.tag_name)).toEqual([
    'meu-v1.0.0',
    'meu-v1.0.0-rc.1',
    'meu-v0.9.0'
  ])
  expect(() => orderedMeuReleases([...f.entries, f.entries[0]])).toThrow('Duplicate')
})

test.each(['signature', 'missing-installer', 'foreign-url', 'wrong-digest'])(
  'preserves older releases when the new publication has %s',
  async fault => {
    const f = fixture(['0.1.0-dev.24', '0.1.0-dev.23', '0.1.0-dev.22', '0.1.0-dev.21'])
    if (fault === 'signature') f.manifests.values().next().value.commit = 'b'.repeat(40)
    if (fault === 'missing-installer') f.entries[0].assets.pop()
    if (fault === 'foreign-url') f.entries[0].assets[0].browser_download_url = 'https://example.com/manifest'
    if (fault === 'wrong-digest') f.entries[0].assets[2].digest = 'sha256:' + 'f'.repeat(64)
    await serverFor(f.entries, async ({ api, removed }) => {
      await expect(pruneMeuReleases({ ...f.source, api, apply: true })).rejects.toThrow()
      expect(removed).toEqual([])
    })
  }
)

test('rechecks identity before deletion and leaves a changed draft intact', async () => {
  const f = fixture(['0.1.0-dev.24', '0.1.0-dev.23', '0.1.0-dev.22', '0.1.0-dev.21'])
  await serverFor(
    f.entries,
    async ({ api, removed }) => {
      await expect(pruneMeuReleases({ ...f.source, api, apply: true })).rejects.toThrow('changed')
      expect(removed).toEqual([])
    },
    entry => ({ ...entry, draft: true })
  )
})

test('reads all inventory pages', async () => {
  const f = fixture(['0.1.0-dev.24', '0.1.0-dev.23'])
  const foreign = Array.from({ length: 99 }, (_, index) => ({
    id: 100 + index,
    tag_name: `v${index}.0.0`,
    draft: false
  }))
  const pages = [[f.entries[0], ...foreign], [f.entries[1]]]
  expect(await readMeuReleaseCatalog(async () => pages.shift())).toEqual(f.entries)
})

test.each([false, true])('selects the newest lower baseline and verifies bytes (corrupt=%s)', async corrupt => {
  const f = fixture(['0.1.0-dev.25', '0.1.0-dev.21', '0.1.0-dev.23', '0.1.0-dev.22'])
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'meu-maintenance-test-'))
  const destination = path.join(root, 'baseline')
  try {
    await serverFor(f.entries, async ({ api, removed }) => {
      const options = {
        ...f.source,
        api,
        fetchArtifact: async () => new Response(corrupt ? Buffer.from('tampered') : f.bytes)
      }
      if (corrupt) {
        await expect(downloadMeuBaseline('0.1.0-dev.24', destination, options)).rejects.toThrow()
        expect(fs.existsSync(destination)).toBe(false)
      } else {
        const baseline = await downloadMeuBaseline('0.1.0-dev.24', destination, options)
        expect(baseline.version).toBe('0.1.0-dev.23')
        expect(verifiedMeuCandidate(destination, f.source.publicKey)).toEqual(baseline)
      }
      expect(removed).toEqual([])
    })
  } finally {
    assert(path.dirname(root) === path.resolve(os.tmpdir()) && path.basename(root).startsWith('meu-maintenance-test-'))
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('the CLI refuses deletion outside the owning workflow before any network call', () => {
  const env = { ...process.env, GITHUB_ACTIONS: '', GITHUB_REPOSITORY: '' }
  const result = spawnSync(
    process.execPath,
    [path.join(import.meta.dirname, 'meu-release-maintenance.mjs'), 'prune', '--apply'],
    { env, encoding: 'utf8', windowsHide: true }
  )
  expect(result.status).toBe(1)
  expect(result.stderr).toContain('restricted to the Meu GitHub workflow')
})
