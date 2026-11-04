// Exercise the actual packaged renderer with the existing fake-backend rehearsal mode.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

import { _electron, expect } from '@playwright/test'

const [executable, scratch] = process.argv.slice(2)
assert(executable && scratch && path.isAbsolute(executable) && path.isAbsolute(scratch), 'Pass absolute executable and scratch paths')
fs.mkdirSync(scratch, { recursive: true })
const resources = path.join(path.dirname(executable), 'resources')
const stamp = JSON.parse(fs.readFileSync(path.join(resources, 'install-stamp.json'), 'utf8'))
assert.deepEqual(
  fs.readFileSync(path.join(resources, 'meu-bootstrap/scripts/install.ps1')),
  fs.readFileSync(new URL('../../../scripts/install.ps1', import.meta.url)),
  'The package must carry the bootstrap script from its own source checkout'
)
const env = Object.fromEntries(Object.entries(process.env).filter(([key, value]) =>
  value !== undefined && !/(?:API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIALS|PRIVATE_KEY)$/.test(key)))
Object.assign(env, {
  MEU_HOME: path.join(scratch, 'profile'),
  HERMES_HOME: path.join(scratch, 'profile'),
  HERMES_DESKTOP_USER_DATA_DIR: path.join(scratch, 'desktop'),
  HERMES_DESKTOP_BOOT_FAKE: '1',
  HERMES_DESKTOP_BOOT_FAKE_STEP_MS: '1',
  HERMES_DESKTOP_SKIP_QUIT_CONFIRM: '1',
  TEST_WORKER_INDEX: '0'
})
delete env.ELECTRON_RUN_AS_NODE
delete env.HERMES_DESKTOP_DEV_SERVER
delete env.HERMES_DESKTOP_HERMES
delete env.HERMES_DESKTOP_HERMES_ROOT

for (const launch of [1, 2]) {
  const app = await _electron.launch({ executablePath: executable, args: ['--disable-gpu'], env, timeout: 60_000 })

  try {
    const isolation = await app.evaluate(() => ({ meu: process.env.MEU_HOME, hermes: process.env.HERMES_HOME }))
    assert.equal(path.resolve(isolation.meu), path.resolve(env.MEU_HOME))
    assert.equal(path.resolve(isolation.hermes), path.resolve(env.HERMES_HOME))
    const page = await app.firstWindow()
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.waitForLoadState('domcontentloaded')
    await expect.poll(() => page.locator('#root').innerText(), { timeout: 60_000 }).not.toBe('')
    await expect(page.getByText('Set up Meu', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: /Install Meu locally/ })).toBeEnabled()
    assert.equal(await page.getByText('Share usage stats?', { exact: true }).count(), 0)
    assert.match(await page.title(), /Meu/)
    const state = await app.evaluate(({ app }) => ({ name: app.getName(), version: app.getVersion(), data: app.getPath('userData') }))
    assert.equal(state.name, 'Meu')
    assert.equal(path.resolve(state.data), path.resolve(env.HERMES_DESKTOP_USER_DATA_DIR))
    if (stamp.meuUpdates?.publicKey) {
      await app.evaluate(() => {
        const original = globalThis.fetch
        globalThis.fetch = async (url, options) => {
          if (String(url) === 'https://api.github.com/repos/rodos4312/Meu-Agent/releases?per_page=50') {
            return new Response('[]', { headers: { 'content-type': 'application/json' } })
          }
          return original(url, options)
        }
      })
      const status = await page.evaluate(() => window.hermesDesktop.updates.check({ force: true }))
      assert.equal(status.supported, true)
      assert.equal(status.updateAvailable, false)
      assert.equal(status.mechanism, 'electron-updater')
      console.log('[PASS] Packaged Meu checks its GitHub release channel with the free trusted update key')
      await app.evaluate(() => {
        const version = '0.1.0-dev.999'
        const file = `Meu-${version}-win-x64.exe`
        const directory = `https://github.com/rodos4312/Meu-Agent/releases/download/meu-v${version}/`
        const manifest = {
          schema: 2, repository: 'rodos4312/Meu-Agent', branch: 'dev/meu-foundation', channel: 'meu-preview',
          publisherName: '', version, commit: 'a'.repeat(40), file, size: 12,
          sha256: 'b'.repeat(64), sha512: Buffer.alloc(64).toString('base64'), signature: Buffer.alloc(64).toString('base64')
        }
        globalThis.fetch = async url => {
          const value = String(url) === 'https://api.github.com/repos/rodos4312/Meu-Agent/releases?per_page=50'
            ? [{ draft: false, tag_name: `meu-v${version}`, assets: ['meu-release.json', 'meu-preview.yml', file].map(name => ({
              name, size: 12, browser_download_url: directory + name
            })) }]
            : String(url) === directory + 'meu-release.json' ? manifest : null
          if (!value) throw new Error('Unexpected update destination in packaged refusal rehearsal')
          return new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } })
        }
      })
      const rejectedCheck = await page.evaluate(() => window.hermesDesktop.updates.check({ force: true }))
      assert.equal(rejectedCheck.error, 'check-failed')
      assert.match(rejectedCheck.message, /signature/)
      const refused = await page.evaluate(() => window.hermesDesktop.updates.apply())
      assert.equal(refused.ok, false)
      assert.match(refused.message, /signature/)
      console.log('[PASS] Packaged Meu rejects a forged release before download or installation')
    } else if (!stamp.meuUpdates) {
      const status = await page.evaluate(() => window.hermesDesktop.updates.check({ force: true }))
      assert.equal(status.supported, false)
      assert.equal(status.reason, 'meu-signing-not-configured')
      const refused = await page.evaluate(() => window.hermesDesktop.updates.apply())
      assert.equal(refused.ok, false)
      assert.equal(refused.error, 'apply-failed')
      assert.match(refused.message, /signing is not configured/)
      console.log('[PASS] Packaged unsigned Meu refuses updater check/download/install')
    }
    assert(!errors.some(error => /Cannot find module|Failed to fetch dynamically imported module|is not defined/.test(error)), errors.join('\n'))
    await page.screenshot({ path: path.join(scratch, `meu-launch-${launch}.png`) })
    fs.writeFileSync(path.join(scratch, `meu-launch-${launch}.json`), JSON.stringify(state, null, 2))
    console.log(`[PASS] Packaged Meu renderer launch ${launch}: ${state.version}`)
  } finally {
    await app.close()
  }
}
