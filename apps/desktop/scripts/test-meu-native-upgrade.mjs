// Disposable Windows rehearsal: real packaged updater + NSIS, controlled release transport.
// The agent backend is deliberately not started; public-feed/backend upgrade testing is separate.
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

import { _electron, expect } from '@playwright/test'
import { gt } from 'semver'

import signing from '../meu-release-signing.cjs'
import trust from '../meu-update-key.json' with { type: 'json' }

assert.equal(process.env.GITHUB_ACTIONS, 'true', 'Native upgrade rehearsal requires a disposable CI runner')
assert.equal(process.env.GITHUB_REPOSITORY, 'rodos4312/Meu-Agent')
assert.equal(process.platform, 'win32')
const [mode, baselineDirectory, candidateDirectory, scratch, executable] = process.argv.slice(2)
for (const directory of [baselineDirectory, candidateDirectory, scratch]) assert(path.isAbsolute(directory))

function verifiedCandidate(directory) {
  const release = JSON.parse(fs.readFileSync(path.join(directory, 'meu-release.json'), 'utf8'))
  signing.verifyRelease(release, trust.publicKey)
  assert.equal(release.repository, 'rodos4312/Meu-Agent')
  assert.equal(release.branch, 'dev/meu-foundation')
  assert.equal(release.channel, 'meu-preview')
  assert.equal(release.file, `Meu-${release.version}-win-x64.exe`)
  const bytes = fs.readFileSync(path.join(directory, release.file))
  assert.equal(bytes.length, release.size)
  assert.equal(createHash('sha256').update(bytes).digest('hex'), release.sha256)
  assert.equal(createHash('sha512').update(bytes).digest('base64'), release.sha512)
  return release
}

const baseline = verifiedCandidate(baselineDirectory)
const release = verifiedCandidate(candidateDirectory)
assert.equal(release.commit, process.env.GITHUB_SHA)
assert(gt(release.version, baseline.version), 'Rehearsal must install a genuinely newer version')
if (mode === 'validate') {
  console.log('[PASS] Both real installers match the pinned Meu key and signed hashes')
  process.exit(0)
}
assert.equal(mode, 'run')
assert(path.isAbsolute(executable))
fs.mkdirSync(scratch, { recursive: true })
const env = Object.fromEntries(
  Object.entries(process.env).filter(
    ([key, value]) => value !== undefined && !/(?:API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIALS|PRIVATE_KEY)$/.test(key)
  )
)
Object.assign(env, {
  MEU_HOME: path.join(scratch, 'profile'),
  HERMES_HOME: path.join(scratch, 'profile'),
  HERMES_DESKTOP_USER_DATA_DIR: path.join(scratch, 'desktop'),
  HERMES_DESKTOP_BOOT_FAKE: '1',
  HERMES_DESKTOP_BOOT_FAKE_STEP_MS: '1',
  HERMES_DESKTOP_SKIP_QUIT_CONFIRM: '1',
  TEST_WORKER_INDEX: '0'
})
for (const key of [
  'ELECTRON_RUN_AS_NODE',
  'HERMES_DESKTOP_DEV_SERVER',
  'HERMES_DESKTOP_HERMES',
  'HERMES_DESKTOP_HERMES_ROOT'
])
  delete env[key]

function profile(action) {
  // Use the real SessionDB schema, with invented chat, memory, skill and key data only.
  const script = `
import os, sys
from pathlib import Path
from hermes_state import SessionDB
p = Path(os.environ['MEU_HOME'])
files = {'.env': 'DEEPSEEK_API_KEY=meu-ci-not-a-real-key\\n',
 'config.yaml': 'model:\\n  provider: deepseek\\n  default: deepseek-v4-flash\\nupdates:\\n  pre_update_backup: false\\n',
 'memories/MEMORY.md': 'Keep this rehearsal memory.\\n',
 'skills/rehearsal/SKILL.md': '---\\nname: rehearsal\\ndescription: CI fixture\\n---\\nKeep this skill.\\n'}
if sys.argv[1] == 'seed':
 p.mkdir(parents=True, exist_ok=True)
 for name, value in files.items():
  f = p / name; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(value, encoding='utf-8')
 db = SessionDB(p / 'state.db')
 db.create_session('meu-upgrade-rehearsal', 'desktop', model='deepseek-v4-flash')
 db.append_message('meu-upgrade-rehearsal', 'user', 'Keep this conversation across the update.')
 db.close()
else:
 for name, value in files.items(): assert (p / name).read_text(encoding='utf-8') == value, name
 db = SessionDB(p / 'state.db', read_only=True)
 assert db.get_messages('meu-upgrade-rehearsal')[0]['content'] == 'Keep this conversation across the update.'
 db.close()
`
  execFileSync(process.env.HERMES_PYTHON, ['-c', script, action], {
    env,
    cwd: path.resolve(import.meta.dirname, '../../..'),
    windowsHide: true
  })
}

async function launch() {
  const app = await _electron.launch({ executablePath: executable, args: ['--disable-gpu'], env, timeout: 60_000 })
  const page = await app.firstWindow()
  app.process().stdout?.on('data', bytes => fs.appendFileSync(path.join(scratch, 'meu-native-app.log'), bytes))
  app.process().stderr?.on('data', bytes => fs.appendFileSync(path.join(scratch, 'meu-native-app.log'), bytes))
  await expect(page.getByText('Set up Meu', { exact: true })).toBeVisible({ timeout: 60_000 })
  const actual = await app.evaluate(({ app }) => ({ version: app.getVersion(), data: app.getPath('userData') }))
  assert.equal(path.resolve(actual.data), path.resolve(env.HERMES_DESKTOP_USER_DATA_DIR))
  return { app, page, version: actual.version }
}

async function installTransport(app) {
  await app.evaluate(
    ({ session }, input) => {
      const fs = process.getBuiltinModule('fs')
      const path = process.getBuiltinModule('path')
      const { Readable, Transform } = process.getBuiltinModule('stream')
      const { release, directory } = input
      const base = `https://github.com/rodos4312/Meu-Agent/releases/download/meu-v${release.version}/`
      const list = 'https://api.github.com/repos/rodos4312/Meu-Agent/releases?per_page=50'
      const state = { mode: 'forged', requests: [] }
      globalThis.meuNativeRehearsal = state
      const original = globalThis.fetch
      globalThis.fetch = async (url, options) => {
        const key = String(url)
        if (key !== list && key !== base + 'meu-release.json') return original(url, options)
        const value =
          key === list
            ? [
                {
                  draft: false,
                  tag_name: `meu-v${release.version}`,
                  assets: ['meu-release.json', 'meu-preview.yml', release.file].map(name => ({
                    name,
                    size: name === release.file ? release.size : 1,
                    browser_download_url: base + name
                  }))
                }
              ]
            : state.mode === 'forged'
              ? { ...release, signature: Buffer.alloc(64).toString('base64') }
              : release
        return new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } })
      }
      // Intercept only the real native updater's session, not its implementation or IPC handlers.
      session.fromPartition('electron-updater', { cache: false }).protocol.handle('https', request => {
        const url = new URL(request.url)
        const canonical = url.origin + url.pathname
        state.requests.push(canonical)
        if (canonical === base + 'meu-preview.yml')
          return new Response(fs.readFileSync(path.join(directory, 'meu-preview.yml')), {
            headers: { 'content-type': 'text/yaml' }
          })
        if (canonical !== base + release.file) throw new Error('Unexpected native upgrade destination: ' + canonical)
        let first = true
        const stream = fs.createReadStream(path.join(directory, release.file)).pipe(
          new Transform({
            transform(chunk, _encoding, done) {
              if (first && state.mode === 'tampered') chunk[0] ^= 1
              first = false
              done(null, chunk)
            }
          })
        )
        return new Response(Readable.toWeb(stream), {
          headers: { 'content-type': 'application/octet-stream', 'content-length': String(release.size) }
        })
      })
    },
    { release, directory: candidateDirectory }
  )
}

async function selectMode(app, mode) {
  await app.evaluate((_electron, mode) => {
    globalThis.meuNativeRehearsal.mode = mode
  }, mode)
}

function powershell(script) {
  return execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], {
    encoding: 'utf8',
    windowsHide: true,
    env: { ...env, MEU_REHEARSAL_EXE: executable }
  }).trim()
}

const running = () =>
  Number(
    powershell(`@(Get-CimInstance Win32_Process -Filter "Name = 'Meu.exe'" | Where-Object {
  $_.ExecutablePath -eq $env:MEU_REHEARSAL_EXE -and $_.CommandLine -notmatch '--type='
}).Count`)
  )

profile('seed')
fs.mkdirSync(env.HERMES_DESKTOP_USER_DATA_DIR, { recursive: true })
fs.writeFileSync(path.join(env.HERMES_DESKTOP_USER_DATA_DIR, 'zoom-state.json'), JSON.stringify({ zoomLevel: 0.25 }))
let current
try {
  current = await launch()
  assert.equal(current.version, baseline.version)
  await expect
    .poll(() =>
      current.app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.getZoomLevel())
    )
    .toBe(0.25)
  await installTransport(current.app)
  const refused = await current.page.evaluate(() => window.hermesDesktop.updates.apply())
  assert.equal(refused.ok, false)
  assert.match(refused.message, /signature/i)
  assert.equal(await current.app.evaluate(() => globalThis.meuNativeRehearsal.requests.length), 0)
  profile('verify')
  await current.page.screenshot({ path: path.join(scratch, 'meu-upgrade-forgery-refused.png') })
  console.log('[PASS] Real installed Meu refuses forged metadata before download')

  await selectMode(current.app, 'tampered')
  const badBytes = await current.page.evaluate(() => window.hermesDesktop.updates.apply())
  assert.equal(badBytes.ok, false)
  assert.match(badBytes.message, /checksum|digest|sha512/i)
  assert.equal(await current.app.evaluate(({ app }) => app.getVersion()), baseline.version)
  profile('verify')
  console.log('[PASS] Real native downloader refuses altered installer bytes and keeps the old app usable')

  await selectMode(current.app, 'valid')
  const available = await current.page.evaluate(() => window.hermesDesktop.updates.check({ force: true }))
  assert.equal(available.updateAvailable, true)
  assert.equal(available.latestTag, `meu-v${release.version}`)
  const closed = current.app.waitForEvent('close', { timeout: 240_000 })
  const applied = await current.page.evaluate(() => window.hermesDesktop.updates.apply())
  assert.equal(applied.ok, true)
  assert.equal(applied.handedOff, true)
  await closed
  current = null

  // The legacy dev.8 installer has a wizard. The disposable-CI driver advances it.
  // New releases use a silent installer only after the explicit Update now choice.
  await expect
    .poll(() => powershell('(Get-Item -LiteralPath $env:MEU_REHEARSAL_EXE).VersionInfo.FileVersion'), {
      timeout: 240_000,
      intervals: [1000]
    })
    .toBe(release.version)
  await expect.poll(running, { timeout: 60_000, intervals: [1000] }).toBe(1)
  console.log('[PASS] Native NSIS handoff installed the new version and relaunched Meu')
  // Reattach deterministically after proving the installer's automatic relaunch.
  powershell(
    'Get-Process -Name Meu -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $env:MEU_REHEARSAL_EXE } | Stop-Process -Force'
  )
  await expect.poll(running, { timeout: 30_000, intervals: [500] }).toBe(0)
  current = await launch()
  assert.equal(current.version, release.version)
  await expect
    .poll(() =>
      current.app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.getZoomLevel())
    )
    .toBe(0.25)
  const stamp = JSON.parse(fs.readFileSync(path.join(path.dirname(executable), 'resources/install-stamp.json'), 'utf8'))
  assert.equal(stamp.commit, release.commit)
  assert.equal(stamp.meuUpdates.publicKey, trust.publicKey)
  profile('verify')
  await current.page.screenshot({ path: path.join(scratch, 'meu-upgrade-complete.png') })
  fs.writeFileSync(
    path.join(scratch, 'meu-native-upgrade.json'),
    JSON.stringify(
      {
        from: baseline.version,
        to: release.version,
        commit: release.commit,
        transport: 'controlled-session',
        realNsis: true,
        publicFeed: false,
        backendStarted: false,
        preserved: ['conversation', 'configuration', 'API-key fixture', 'memory', 'skill', 'desktop zoom']
      },
      null,
      2
    )
  )
  console.log('[PASS] Updated renderer reopened; real SessionDB conversation, settings, key, memory and skill survived')
} finally {
  if (current) await current.app.close().catch(() => {})
  fs.writeFileSync(path.join(scratch, '.native-upgrade-done'), '')
}
