// Exercise the actual packaged renderer with the existing fake-backend rehearsal mode.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

import { _electron, expect } from '@playwright/test'

const [executable, scratch] = process.argv.slice(2)
assert(executable && scratch && path.isAbsolute(executable) && path.isAbsolute(scratch), 'Pass absolute executable and scratch paths')
fs.mkdirSync(scratch, { recursive: true })
const stamp = JSON.parse(fs.readFileSync(path.join(path.dirname(executable), 'resources/install-stamp.json'), 'utf8'))
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
    if (!stamp.meuUpdates) {
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
