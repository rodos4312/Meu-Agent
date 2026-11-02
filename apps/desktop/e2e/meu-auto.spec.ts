import fs from 'node:fs'
import path from 'node:path'

import { writeMockProviderConfig } from '../../../tests-js/scripts/mock-provider-config'
import { startMockServer } from '../../../tests-js/scripts/mock-server'

import { buildAppEnv, createSandbox, launchDesktop, type MockBackendFixture, waitForAppReady } from './fixtures'
import { expect, test } from './test'

test('Auto is visible in new sessions and Bots, survives reload and sends concrete models', async () => {
  test.setTimeout(180_000)
  const mock = await startMockServer({ extraModels: ['deepseek-v4-pro', 'deepseek-flash'] })
  const sandbox = createSandbox('meu-auto')
  writeMockProviderConfig(
    sandbox.hermesHome,
    mock.url,
    undefined,
    JSON.stringify({
      model: { provider: 'deepseek', default: 'deepseek-v4-pro', base_url: `${mock.url}/v1`, context_length: 64000 },
      smart_model_routing: { enabled: true }
    })
  )
  fs.writeFileSync(path.join(sandbox.hermesHome, '.env'), 'DEEPSEEK_API_KEY=e2e-fixture-only\n')
  const launched = await launchDesktop(buildAppEnv(sandbox))
  const fixture = { ...launched, sandbox, mock, mockUrl: mock.url } as MockBackendFixture
  const { page, app } = fixture
  try {
    expect(await app.evaluate(() => process.env.MEU_HOME)).toBe(sandbox.hermesHome)
    expect(await app.evaluate(() => process.env.HERMES_HOME)).toBe(sandbox.hermesHome)
    await waitForAppReady(fixture, 90_000)
    const composer = page.locator('[data-slot="composer-root"]').filter({ visible: true }).first()
    const input = composer.locator('[contenteditable="true"]').first()
    await expect(composer).toContainText('Auto · Flash / Pro')
    const send = async (text: string, model: string) => {
      const count = mock.receivedModels.length
      await input.fill(text)
      await input.press('Enter')
      await expect.poll(() => mock.receivedModels.length, { timeout: 30_000 }).toBeGreaterThan(count)
      expect(mock.receivedModels.slice(count)).toContain(model)
      expect(mock.receivedModels).not.toContain('deepseek-auto')
      await expect(input).toBeEditable({ timeout: 30_000 })
      await expect(page.locator('[data-slot="aui_thread-viewport"]').filter({ visible: true }).first()).toContainText(
        'Hello from the mock inference server!'
      )
      await expect(page.getByRole('button', { name: 'Stop', exact: true })).toHaveCount(0)
    }
    await send('hello', 'deepseek-flash')
    await composer.getByRole('button').filter({ hasText: 'Auto · Flash / Pro' }).click()
    await page
      .getByRole('menuitem', { name: /DeepSeek V4 Pro/ })
      .first()
      .click()
    await expect(composer).toContainText('DeepSeek V4 Pro')
    await send('hello again', 'deepseek-v4-pro')
    await composer.getByRole('button').filter({ hasText: 'DeepSeek V4 Pro' }).click()
    await page
      .getByRole('menuitem', { name: /Auto · Flash \/ Pro/ })
      .first()
      .click()
    await expect(composer).toContainText('Auto · Flash / Pro')
    await page.reload()
    await waitForAppReady(fixture, 90_000)
    await expect(composer).toContainText('Auto · Flash / Pro')
    await send('Debug this Python code', 'deepseek-v4-pro')
    await page
      .getByRole('button', { name: /^Bots$/i })
      .or(page.getByRole('tab', { name: /^Bots$/i }))
      .first()
      .click()
    await page.locator('[data-roster-key]').filter({ hasText: 'Meu' }).first().click()
    await expect(page.getByText('Say something to get started.', { exact: true })).toBeVisible({ timeout: 60_000 })
    await expect(page.locator('[data-slot="aui_thread-viewport"]').filter({ visible: true }).first()).not.toContainText(
      'Debug this Python code'
    )
    await expect(composer).toContainText('Auto · Flash / Pro', { timeout: 30_000 })
    await composer.getByRole('button').filter({ hasText: 'Auto · Flash / Pro' }).click()
    await page
      .getByRole('menuitem', { name: /DeepSeek.*Flash/i })
      .first()
      .click()
    await expect(composer).not.toContainText('Auto · Flash / Pro')
    await send('A short bot greeting', 'deepseek-flash')
    await composer.getByRole('button').filter({ hasText: 'DeepSeek' }).first().click()
    await page
      .getByRole('menuitem', { name: /Auto · Flash \/ Pro/ })
      .first()
      .click()
    await expect(composer).toContainText('Auto · Flash / Pro')
    await page.screenshot({ path: test.info().outputPath('meu-auto-bot.png') })
  } finally {
    await app.close().catch(() => undefined)
    await mock.close()
    sandbox.cleanup()
  }
})
