import fs from 'node:fs'
import path from 'node:path'

import yaml from 'js-yaml'

import { buildAppEnv, launchDesktop, type MockBackendFixture, setupMockBackend, waitForAppReady } from './fixtures'
import { expect, test } from './test'

let fixture: MockBackendFixture

test.beforeAll(async () => {
  fixture = await setupMockBackend()
})

test.afterAll(async () => {
  await fixture?.cleanup()
})

test('Meu Coordinator can be selected and persists through a real desktop restart', async () => {
  test.setTimeout(120_000)
  const { app, page, sandbox } = fixture
  expect(await app.evaluate(() => process.env.MEU_HOME)).toBe(sandbox.hermesHome)
  expect(await app.evaluate(() => process.env.HERMES_HOME)).toBe(sandbox.hermesHome)
  await waitForAppReady(fixture, 90_000)
  await page.locator('[data-meu-nav="settings"]').click()
  await page.locator('[data-tour="nav-config:model:delegation"]').click()
  const option = page.locator('[data-mode="meu_coordinator"] button[role="radio"]')
  await expect(option).toContainText('Meu Coordinator')
  await option.click()
  await expect(option).toHaveAttribute('aria-checked', 'true')
  const config = () =>
    yaml.load(fs.readFileSync(path.join(sandbox.hermesHome, 'config.yaml'), 'utf8')) as {
      delegation?: { backend?: string }
    }
  await expect.poll(() => config().delegation?.backend).toBe('meu_coordinator')
  await page.screenshot({ path: test.info().outputPath('meu-coordinator-settings.png') })
  await app.close()

  const reopened = await launchDesktop(buildAppEnv(sandbox))
  try {
    await waitForAppReady({ ...fixture, ...reopened }, 90_000)
    await reopened.page.locator('[data-meu-nav="settings"]').click()
    await reopened.page.locator('[data-tour="nav-config:model:delegation"]').click()
    await expect(reopened.page.locator('[data-mode="meu_coordinator"] button[role="radio"]')).toHaveAttribute(
      'aria-checked',
      'true'
    )
    await reopened.page.screenshot({ path: test.info().outputPath('meu-coordinator-reopened.png') })
  } finally {
    await reopened.app.close()
  }
})
