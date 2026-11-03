// Uses installed app/backend; only release transport and NEW startup failure are controlled.
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { _electron, expect } from '@playwright/test'
import { gt } from 'semver'
import { installMeuUpgradeTransport, verifiedMeuCandidate } from './meu-upgrade-transport.mjs'
import trust from '../meu-update-key.json' with { type: 'json' }

assert.equal(process.env.GITHUB_ACTIONS, 'true')
assert.equal(process.env.GITHUB_REPOSITORY, 'rodos4312/Meu-Agent')
assert.equal(process.platform, 'win32')
const [mode, baselineDirectory, directory, scratch, executable, root, launcher] = process.argv.slice(2)
for (const value of [baselineDirectory, directory, scratch]) assert(path.isAbsolute(value))
const baseline = verifiedMeuCandidate(baselineDirectory, trust.publicKey)
const release = verifiedMeuCandidate(directory, trust.publicKey)
assert.equal(baseline.commit, process.env.GITHUB_SHA)
assert.equal(release.commit, baseline.commit)
assert(gt(release.version, baseline.version))
if (mode === 'validate') process.exit(0)
assert.equal(mode, 'run')
for (const value of [executable, root, launcher]) assert(path.isAbsolute(value))
const env = Object.fromEntries(
  Object.entries(process.env).filter(
    ([key, value]) => value !== undefined && !/(?:API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIALS|PRIVATE_KEY)$/.test(key)
  )
)
Object.assign(env, {
  HERMES_DESKTOP_USER_DATA_DIR: path.join(scratch, 'desktop'),
  HERMES_DESKTOP_SKIP_QUIT_CONFIRM: '1',
  TEST_WORKER_INDEX: '0'
})
for (const key of [
  'ELECTRON_RUN_AS_NODE',
  'PYTHONPATH',
  'VIRTUAL_ENV',
  'HERMES_PYTHON',
  'HERMES_DESKTOP_BOOT_FAKE',
  'HERMES_DESKTOP_BOOT_FAKE_ERROR',
  'HERMES_DESKTOP_DEV_SERVER',
  'HERMES_DESKTOP_HERMES_ROOT',
  'HERMES_DESKTOP_HERMES'
])
  delete env[key]
const runtime = JSON.parse(
  execFileSync(launcher, ['--print-runtime-command'], { env, cwd: root, encoding: 'utf8', windowsHide: true })
)
// The launcher exposes its canonical base Python. Bootstrap selects/leases its dependencies.
const python = Array.isArray(runtime) ? runtime[0] : undefined
assert.equal(typeof python, 'string')
assert(path.isAbsolute(python))
const bootstrap = `import sys;sys.path.insert(0,${JSON.stringify(root)});import hermes_bootstrap;`
function profile(action) {
  execFileSync(
    python,
    [
      '-I',
      '-c',
      bootstrap +
        `
import os,sqlite3
from pathlib import Path
from hermes_state import SessionDB
p=Path(os.environ['MEU_HOME'])
files={'.env':'DEEPSEEK_API_KEY=meu-ci-not-a-real-key\\n',
 'config.yaml':'model:\\n  provider: deepseek\\n  default: deepseek-flash\\nupdates:\\n  pre_update_backup: true\\n',
 'memories/MEMORY.md':'Keep rollback memory.\\n','skills/rehearsal/SKILL.md':'---\\nname: rehearsal\\ndescription: CI fixture\\n---\\nKeep rollback skill.\\n'}
if ${JSON.stringify(action)}=='seed':
 for name,value in files.items():
  f=p/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(value,encoding='utf-8')
 db=SessionDB(p/'state.db');db.create_session('rollback-fixture','desktop',model='deepseek-flash')
 db.append_message('rollback-fixture','user','Preserve this conversation.');db.close()
else:
 for name,value in files.items(): assert (p/name).read_text(encoding='utf-8')==value,name
 db=SessionDB(p/'state.db',read_only=True)
 assert db.get_messages('rollback-fixture')[0]['content']=='Preserve this conversation.';db.close()
 with sqlite3.connect(p/'state.db') as db:
  assert 'meu_failed_version' not in [r[1] for r in db.execute('PRAGMA table_info(messages)')]
`
    ],
    { env, cwd: root, windowsHide: true, timeout: 60_000 }
  )
}
function cli(...args) {
  return execFileSync(launcher, args, { env, cwd: root, encoding: 'utf8', windowsHide: true, timeout: 300_000 }).trim()
}
const transaction = () => {
  const parent = path.join(env.MEU_HOME, 'backups')
  if (!fs.existsSync(parent)) return null
  const entries = fs.readdirSync(parent).filter(name => /^meu-update-[a-f0-9]{32}$/.test(name))
  if (entries.length !== 1) return null
  const location = path.join(parent, entries[0])
  return { location, ...JSON.parse(fs.readFileSync(path.join(location, 'transaction.json'), 'utf8')) }
}
let app
let phase = 'seed isolated profile'
try {
  profile('seed')
  app = await _electron.launch({ executablePath: executable, args: ['--disable-gpu'], env, timeout: 90_000 })
  const page = await app.firstWindow()
  const log = bytes => fs.appendFileSync(path.join(scratch, 'desktop.log'), bytes)
  app.process().stdout?.on('data', log)
  app.process().stderr?.on('data', log)
  assert.equal(await app.evaluate(({ app }) => app.getVersion()), baseline.version)
  await expect.poll(() => page.evaluate(() => Boolean(window.hermesDesktop?.updates)), { timeout: 120_000 }).toBe(true)
  const initial = JSON.parse(cli('gateway', 'ensure', '--json'))
  assert.equal(initial.state, 'ready')
  assert.equal(initial.endpoint.code_sha, baseline.commit)
  await installMeuUpgradeTransport(app, {
    release,
    directory,
    baseline,
    baselineDirectory,
    mode: 'valid',
    failOnRestart: true,
    migrationPython: python
  })
  phase = 'native handoff with armed recovery'
  const closed = app.waitForEvent('close', { timeout: 180_000 })
  void closed.catch(() => {})
  const result = await page.evaluate(() => window.hermesDesktop.updates.apply())
  assert.equal(result.ok, true, result.message)
  assert.equal(result.handedOff, true)
  await closed
  app = null
  phase = 'automatic package and database recovery'
  await expect.poll(() => transaction()?.state, { timeout: 600_000, intervals: [1000] }).toBe('rolled-back')
  const record = transaction()
  assert(fs.statSync(path.join(record.location, 'failed-state.zip')).size > 0)
  assert.equal(record.restoredCommit, baseline.commit)
  phase = 'verify restored gateway and conversation'
  const restored = JSON.parse(cli('gateway', 'ensure', '--json'))
  assert.equal(restored.state, 'ready')
  assert.equal(restored.endpoint.code_sha, baseline.commit)
  profile('verify')
  const actual = execFileSync(
    'powershell.exe',
    [
      '-NoProfile',
      '-NonInteractive',
      '-Command',
      '(Get-Item -LiteralPath $env:MEU_REHEARSAL_EXE).VersionInfo.FileVersion'
    ],
    {
      env: { ...env, MEU_REHEARSAL_EXE: executable },
      windowsHide: true,
      encoding: 'utf8',
      timeout: 30_000
    }
  ).trim()
  assert.equal(actual, baseline.version)
  fs.writeFileSync(
    path.join(scratch, 'result.json'),
    JSON.stringify(
      {
        from: baseline.version,
        rejected: release.version,
        restored: actual,
        realNsis: true,
        realGateway: true,
        restoredDatabaseSchema: true,
        preserved: ['conversation', 'configuration', 'API-key fixture', 'memory', 'skill'],
        failedStateRetained: true,
        publicRelease: false
      },
      null,
      2
    )
  )
  console.log(
    '[PASS] Failed startup automatically restored verified desktop, real backend and pre-update database; fixture data survived.'
  )
} catch (error) {
  const record = transaction()
  fs.writeFileSync(
    path.join(scratch, 'failure.json'),
    JSON.stringify({ phase, error: error.message, recoveryState: record?.state, recoveryError: record?.error }, null, 2)
  )
  if (record)
    for (const name of ['watch.log']) {
      const file = path.join(record.location, name)
      if (fs.existsSync(file)) fs.copyFileSync(file, path.join(scratch, name))
    }
  throw error
} finally {
  if (app) await app.close().catch(() => app.process().kill())
}
