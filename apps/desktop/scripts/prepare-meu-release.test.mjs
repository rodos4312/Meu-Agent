import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { test } from 'vitest'
import { dump } from 'js-yaml'

import { prepareMeuRelease } from './prepare-meu-release.mjs'
import policy from '../meu-release.cjs'
import { buildStampPayload } from './write-build-stamp.mjs'

test('preview builds have no trusted update publisher; signing inputs are explicit and never contain credentials', () => {
  assert.equal(policy.meuReleasePolicy({}), null)
  assert.throws(() => policy.meuReleasePolicy({ MEU_SIGNED_RELEASE: '1' }), /certificate subject/)
  assert.throws(
    () =>
      policy.meuReleasePolicy({
        MEU_SIGNED_RELEASE: '1',
        MEU_WINDOWS_PUBLISHER: 'CN=Meu',
        AZURE_CLIENT_ID: 'upstream'
      }),
    /upstream/
  )
  const env = {
    MEU_SIGNED_RELEASE: '1',
    MEU_WINDOWS_PUBLISHER: 'CN=Meu Test Publisher',
    WIN_CSC_LINK: 'secret fixture',
    WIN_CSC_KEY_PASSWORD: 'never stamped'
  }
  const stamp = buildStampPayload(
    { commit: 'a'.repeat(40), branch: policy.BRANCH, source: 'ci', dirty: false },
    env,
    'win32'
  )
  assert.equal(stamp.meuUpdates.repository, policy.REPOSITORY)
  assert.equal(stamp.meuUpdates.publisherName, env.MEU_WINDOWS_PUBLISHER)
  assert.ok(!JSON.stringify(stamp).includes('secret fixture'))
  assert.ok(!JSON.stringify(stamp).includes('never stamped'))
  assert.throws(
    () => buildStampPayload({ commit: 'a'.repeat(40), branch: 'main', source: 'ci', dirty: false }, env, 'win32'),
    /development branch/
  )
  const tagStamp = buildStampPayload(
    { commit: 'a'.repeat(40), branch: 'meu-release-request-0.1.0-dev.8', source: 'ci', dirty: false },
    {
      ...env,
      GITHUB_REPOSITORY: policy.REPOSITORY,
      GITHUB_SHA: 'a'.repeat(40),
      GITHUB_REF_NAME: 'meu-release-request-0.1.0-dev.8'
    },
    'win32'
  )
  assert.equal(tagStamp.branch, policy.BRANCH)
})

test('release preparation binds native feed to the exact scanned and signed installer, and refuses failed evidence', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'meu-release-'))
  try {
    const version = '0.1.0-dev.8'
    const installer = path.join(root, `Meu-${version}-win-x64.exe`)
    const bytes = Buffer.from('benign nonexecutable release fixture')
    fs.writeFileSync(installer, bytes)
    const sha256 = createHash('sha256').update(bytes).digest('hex')
    const sha512 = createHash('sha512').update(bytes).digest('base64')
    const report = {
      file: path.basename(installer),
      bytes: bytes.length,
      sha256,
      sha512,
      status: 'clean',
      scans: [{ exitCode: 0 }, { exitCode: 0 }],
      signature: { status: 'Valid', type: 'Authenticode', subject: 'CN=Meu Test Publisher' }
    }
    const stamp = {
      branch: policy.BRANCH,
      commit: 'a'.repeat(40),
      dirty: false,
      meuUpdates: {
        repository: policy.REPOSITORY,
        branch: policy.BRANCH,
        channel: policy.CHANNEL,
        publisherName: report.signature.subject
      }
    }
    const feed = path.join(root, 'feed.yml')
    fs.writeFileSync(feed, dump({ version, files: [{ url: path.basename(installer), sha512 }] }))
    const args = { installer, version, report, stamp, feed, output: path.join(root, 'candidate') }
    const manifest = prepareMeuRelease(args)
    assert.equal(manifest.sha256, sha256)
    assert.equal(manifest.commit, stamp.commit)
    assert.ok(fs.existsSync(path.join(args.output, 'meu-release.json')))
    for (const changed of [
      { status: 'failed' },
      { sha256: 'b'.repeat(64) },
      { signature: { ...report.signature, subject: 'CN=Someone Else' } }
    ]) {
      assert.throws(() => prepareMeuRelease({ ...args, report: { ...report, ...changed } }), /evidence/)
    }
    assert.throws(() => prepareMeuRelease({ ...args, stamp: { ...stamp, dirty: true } }), /clean/)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})
