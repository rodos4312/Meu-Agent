// Disposable Windows rehearsal: real packaged updater + NSIS, controlled release transport.
// The agent backend is deliberately not started; public-feed/backend upgrade testing is separate.
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

import { _electron, expect } from '@playwright/test'
import { gt } from 'semver'

import { installMeuUpgradeTransport, verifiedMeuCandidate } from './meu-upgrade-transport.mjs'
import trust from '../meu-update-key.json' with { type: 'json' }

assert.equal(process.env.GITHUB_ACTIONS, 'true', 'Native upgrade rehearsal requires a disposable CI runner')
assert.equal(process.env.GITHUB_REPOSITORY, 'rodos4312/Meu-Agent')
assert.equal(process.platform, 'win32')
const [mode, baselineDirectory, candidateDirectory, scratch, executable] = process.argv.slice(2)
for (const directory of [baselineDirectory, candidateDirectory, scratch]) assert(path.isAbsolute(directory))

const baseline = verifiedMeuCandidate(baselineDirectory, trust.publicKey)
const release = verifiedMeuCandidate(candidateDirectory, trust.publicKey)
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
  try {
    const page = await app.firstWindow()
    const record = bytes =>
      fs.appendFileSync(path.join(scratch, 'meu-native-app.log'), `[${new Date().toISOString()}] ${bytes}`)
    app.process().stdout?.on('data', record)
    app.process().stderr?.on('data', record)
    await expect(page.getByText('Set up Meu', { exact: true })).toBeVisible({ timeout: 60_000 })
    const actual = await app.evaluate(({ app }) => ({ version: app.getVersion(), data: app.getPath('userData') }))
    assert.equal(path.resolve(actual.data), path.resolve(env.HERMES_DESKTOP_USER_DATA_DIR))
    return { app, page, version: actual.version }
  } catch (error) {
    await bounded('failed launch cleanup', app.close(), 15_000).catch(() => app.process().kill())
    throw error
  }
}

async function installTransport(app) {
  await installMeuUpgradeTransport(app, { release, directory: candidateDirectory })
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
    timeout: 15_000,
    env: { ...env, MEU_REHEARSAL_EXE: executable }
  }).trim()
}

async function bounded(label, work, milliseconds = 120_000) {
  let timer
  try {
    return await Promise.race([
      work,
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`Native rehearsal timed out: ${label}`)), milliseconds)
      })
    ])
  } finally {
    clearTimeout(timer)
  }
}

const running = () =>
  Number(
    powershell(`@(Get-CimInstance Win32_Process -OperationTimeoutSec 5 -Filter "Name = 'Meu.exe'" | Where-Object {
  $_.ExecutablePath -eq $env:MEU_REHEARSAL_EXE -and $_.CommandLine -notmatch '--type='
}).Count`)
  )

profile('seed')
fs.mkdirSync(env.HERMES_DESKTOP_USER_DATA_DIR, { recursive: true })
fs.writeFileSync(path.join(env.HERMES_DESKTOP_USER_DATA_DIR, 'zoom-state.json'), JSON.stringify({ zoomLevel: 0.25 }))
let current
let phase = 'launch baseline'
try {
  current = await launch()
  assert.equal(current.version, baseline.version)
  await expect
    .poll(() =>
      current.app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.getZoomLevel())
    )
    .toBe(0.25)
  await installTransport(current.app)
  phase = 'reject forged metadata'
  const refused = await bounded(
    phase,
    current.page.evaluate(() => window.hermesDesktop.updates.apply())
  )
  assert.equal(refused.ok, false)
  assert.match(refused.message, /signature/i)
  assert.equal(await current.app.evaluate(() => globalThis.meuNativeRehearsal.requests.length), 0)
  profile('verify')
  await current.page.screenshot({ path: path.join(scratch, 'meu-upgrade-forgery-refused.png') })
  console.log('[PASS] Real installed Meu refuses forged metadata before download')

  await selectMode(current.app, 'tampered')
  phase = 'reject tampered download'
  const badBytes = await bounded(
    phase,
    current.page.evaluate(() => window.hermesDesktop.updates.apply())
  )
  assert.equal(badBytes.ok, false)
  assert.match(badBytes.message, /checksum|digest|sha512/i)
  assert.equal(await current.app.evaluate(({ app }) => app.getVersion()), baseline.version)
  profile('verify')
  console.log('[PASS] Real native downloader refuses altered installer bytes and keeps the old app usable')

  await selectMode(current.app, 'valid')
  phase = 'check valid candidate'
  const available = await bounded(
    phase,
    current.page.evaluate(() => window.hermesDesktop.updates.check({ force: true }))
  )
  assert.equal(available.updateAvailable, true)
  assert.equal(available.latestTag, `meu-v${release.version}`)
  const closed = current.app.waitForEvent('close', { timeout: 120_000 })
  void closed.catch(() => {})
  phase = 'native download and handoff'
  console.log('[REHEARSAL] Applying the valid update through the real native client')
  const applied = await bounded(
    phase,
    current.page.evaluate(() => window.hermesDesktop.updates.apply())
  )
  assert.equal(applied.ok, true)
  assert.equal(applied.handedOff, true)
  console.log('[REHEARSAL] Native apply acknowledged the installer handoff')
  phase = 'old process exit'
  await bounded(phase, closed)
  current = null
  console.log('[REHEARSAL] Old app process exited without forcing it')

  phase = 'installed executable version'
  await expect
    .poll(() => powershell('(Get-Item -LiteralPath $env:MEU_REHEARSAL_EXE).VersionInfo.FileVersion'), {
      timeout: 240_000,
      intervals: [1000]
    })
    .toBe(release.version)
  console.log('[REHEARSAL] Installed executable reports the target version')
  phase = 'installer automatic relaunch'
  await expect.poll(running, { timeout: 60_000, intervals: [1000] }).toBe(1)
  console.log('[PASS] Native NSIS handoff installed the new version and relaunched Meu')
  // Reattach deterministically after proving the installer's automatic relaunch.
  powershell(
    'Get-Process -Name Meu -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $env:MEU_REHEARSAL_EXE } | Stop-Process -Force'
  )
  await expect.poll(running, { timeout: 30_000, intervals: [500] }).toBe(0)
  phase = 'reopen target and verify data'
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
} catch (error) {
  fs.writeFileSync(
    path.join(scratch, 'meu-native-upgrade-failure.json'),
    JSON.stringify({ phase, error: error.message }, null, 2)
  )
  throw error
} finally {
  if (current) await bounded('fixture shutdown', current.app.close(), 15_000).catch(() => current.app.process().kill())
}
