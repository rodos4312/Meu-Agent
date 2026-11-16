import assert from 'node:assert/strict'
import { test } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import {createHash} from 'node:crypto'
import {readSourceSeed, buildStampPayload} from './write-build-stamp.mjs'

import {
  FALLBACK_BRANCH,
  FALLBACK_COMMIT,
  fromCI,
  fromFallback,
  fromLocalGit,
  isFallbackCommit,
  resolveStamp
} from './write-build-stamp.mjs'

test('fromCI reads GITHUB_SHA / GITHUB_REF_NAME', () => {
  assert.deepEqual(
    fromCI({ GITHUB_SHA: 'a'.repeat(40), GITHUB_REF_NAME: 'release' }),
    { commit: 'a'.repeat(40), branch: 'release', dirty: false, source: 'ci' }
  )
  assert.equal(fromCI({}), null)
})

test('fromLocalGit reads HEAD + branch + dirty status', () => {
  const calls = []
  const execFn = (argv) => {
    const cmd = argv.join(' ')
    calls.push(cmd)
    if (cmd === 'git rev-parse HEAD') return 'b'.repeat(40)
    if (cmd === 'git rev-parse --abbrev-ref HEAD') return 'main'
    if (cmd === 'git status --porcelain -uno') return ' M apps/desktop/package.json'
    return null
  }
  assert.deepEqual(fromLocalGit('/repo', execFn), {
    commit: 'b'.repeat(40),
    branch: 'main',
    dirty: true,
    source: 'local'
  })
  assert.ok(calls.includes('git rev-parse HEAD'))
})

test('fromFallback uses the all-zero placeholder commit', () => {
  assert.deepEqual(fromFallback(), {
    commit: FALLBACK_COMMIT,
    branch: FALLBACK_BRANCH,
    dirty: false,
    source: 'fallback'
  })
  assert.equal(isFallbackCommit(FALLBACK_COMMIT), true)
  assert.equal(isFallbackCommit('a'.repeat(40)), false)
})

test('resolveStamp prefers CI over local git over fallback', () => {
  const ci = resolveStamp({
    env: { GITHUB_SHA: 'c'.repeat(40), GITHUB_REF_NAME: 'main' },
    execFn: () => 'should-not-run'
  })
  assert.equal(ci.source, 'ci')
  assert.equal(ci.commit, 'c'.repeat(40))

  const local = resolveStamp({
    env: {},
    execFn: (argv) => {
      const cmd = argv.join(' ')
      if (cmd === 'git rev-parse HEAD') return 'd'.repeat(40)
      if (cmd === 'git rev-parse --abbrev-ref HEAD') return 'main'
      if (cmd === 'git status --porcelain -uno') return ''
      return null
    }
  })
  assert.equal(local.source, 'local')
  assert.equal(local.commit, 'd'.repeat(40))
  assert.equal(local.dirty, false)
})

test('resolveStamp falls back when neither CI nor git is available', () => {
  const stamp = resolveStamp({ env: {}, execFn: () => null })
  assert.deepEqual(stamp, {
    commit: FALLBACK_COMMIT,
    branch: FALLBACK_BRANCH,
    dirty: false,
    source: 'fallback'
  })
})

// ── buildStampPayload — the staged-desktop full schema ─────────────────────

import { buildStampPayload } from './write-build-stamp.mjs'

const baseStamp = {
  commit: 'c'.repeat(40),
  branch: 'dev/meu-foundation',
  builtAt: '2026-08-14T00:00:00Z',
  dirty: false,
  source: 'ci'
}

const runtime = {
  repoDir: 'app', toolsDir: 'tools', storePython: 'tools/python/bin/python3',
  sitePackages: 'venv/lib/python3.14/site-packages', commands: { hermes: 'bin/hermes' }
}

test('bundled stamp carries the builder contract and refuses an unstaged payload', () => {
  const env = { HERMES_DESKTOP_VARIANT: 'bundled' }
  assert.throws(() => buildStampPayload(baseStamp, env, 'darwin'), /payload/)
  assert.deepEqual(buildStampPayload(baseStamp, env, 'darwin', { runtime }).runtime, runtime)
  assert.equal(buildStampPayload(baseStamp, { HERMES_DESKTOP_VARIANT: 'light' }, 'darwin', { runtime }).runtime, undefined)
})

test('source builds declare the same artifact schema, without a payload', () => {
  const stamp = buildStampPayload(baseStamp, {})
  assert.equal(stamp.payload, 'bootstrap')
  assert.equal(stamp.distribution, 'desktop-app')
  assert.equal(stamp.runtime, undefined)
  assert.equal(stamp.tag, null)
  assert.equal(stamp.commit, baseStamp.commit)
})

test('buildStampPayload keeps schemaVersion + provenance in the staged shape', () => {
  const payload = buildStampPayload(baseStamp, {
    HERMES_DESKTOP_VARIANT: 'bundled'
  }, 'win32', { runtime })
  assert.equal(payload.schemaVersion, 1)
  assert.equal(payload.commit, baseStamp.commit)
  assert.equal(payload.source, 'ci')
  assert.equal(payload.tag, null)
})

test('commit builds retain exact provenance without entering an update channel', () => {
  for (const platform of ['win32', 'darwin']) {
    const env = { HERMES_DESKTOP_VARIANT: 'bundled', HERMES_BUILD_COMMIT: baseStamp.commit }
    const payload = buildStampPayload(baseStamp, env, platform, { runtime })
    assert.equal(payload.commit, baseStamp.commit)
    assert.equal(payload.source, 'commit-build')
    assert.equal(payload.branch, null)
    assert.equal(payload.tag, null)
    assert.equal(payload.updateMechanism, 'external')
    assert.throws(() => buildStampPayload(baseStamp, { ...env, HERMES_BUILD_COMMIT: 'a'.repeat(40) }, platform, { runtime }), /commit/i)
    assert.throws(() => buildStampPayload(baseStamp, { ...env, HERMES_PAYLOAD_TAG: 'v1.2.3' }, platform, { runtime }), /tag/i)
  }
})



test('private bootstrap records the source bytes and refuses stale/tampered packages', () => {
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'meu-seed-stamp-'))
  try {
    const commit='a'.repeat(40), bytes=Buffer.from('real fixture bytes')
    const seed={schema:1,file:'meu-source-seed.zip',commit,base:'b'.repeat(40),
      branch:'dev/meu-foundation',repository:'https://github.com/rodos4312/Meu-Agent-RC-private.git',
      sha256:createHash('sha256').update(bytes).digest('hex'),size:bytes.length}
    fs.writeFileSync(path.join(directory,seed.file),bytes)
    fs.writeFileSync(path.join(directory,'meu-source-seed.json'),JSON.stringify(seed))
    assert.deepEqual(readSourceSeed(directory,commit),seed)
    const stamp=buildStampPayload({commit,branch:'rc/meu-small-rc3',dirty:false,source:'ci'},
      {MEU_UPDATE_CHANNEL:'rc',HERMES_DESKTOP_VARIANT:''},'win32',null,seed)
    assert.equal(stamp.updateMechanism,'app-installer')
    assert.equal(stamp.payload,'bootstrap')
    assert.deepEqual(stamp.sourceSeed,seed)
    const publicSeed={...seed,repository:'https://github.com/rodos4312/Meu-Agent.git'}
    const publicStamp=buildStampPayload({commit,branch:'dev/meu-foundation',dirty:false,source:'ci'},
      {HERMES_DESKTOP_VARIANT:''},'win32',null,publicSeed)
    assert.equal(publicStamp.meuUpdates.repository,'rodos4312/Meu-Agent')
    assert.equal(publicStamp.sourceSeed.repository,publicSeed.repository)
    assert.throws(()=>buildStampPayload({commit,branch:'dev/meu-foundation',dirty:false,source:'ci'},
      {HERMES_DESKTOP_VARIANT:''},'win32',null,seed),/matching repository authority/)
    assert.throws(()=>readSourceSeed(directory,'c'.repeat(40)),/identity/)
    fs.writeFileSync(path.join(directory,seed.file),'altered')
    assert.throws(()=>readSourceSeed(directory,commit),/checksum/)
  } finally {fs.rmSync(directory,{recursive:true,force:true})}
})
