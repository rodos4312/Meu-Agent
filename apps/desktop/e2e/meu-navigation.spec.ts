import { runDesktopChatSmoke } from '../../../tests-js/scripts/desktop-chat-smoke'

import { type MockBackendFixture, setupMockBackend, waitForAppReady } from './fixtures'
import { expect, test } from './test'

let fixture: MockBackendFixture

test.beforeAll(async () => {
  fixture = await setupMockBackend()
})

test.afterAll(async () => {
  await fixture?.cleanup()
})

test('Meu navigation preserves the live composer and stays usable across pages and window sizes', async () => {
  test.setTimeout(180_000)
  const { app, page } = fixture
  // Fail before interacting if a product-specific resolver escapes the sandbox.
  expect(await app.evaluate(() => process.env.HERMES_HOME)).toBe(fixture.sandbox.hermesHome)
  expect(await app.evaluate(() => process.env.MEU_HOME)).toBe(fixture.sandbox.hermesHome)
  await waitForAppReady(fixture, 90_000)
  await expect(page.locator('[data-slot="aui_intro"]')).toBeVisible()
  await expect(page.locator('[data-slot="session-row"]')).toHaveCount(0)
  await expect(page.locator('[data-slot="composer-root"]')).toContainText('Mock Model')
  const rail = page.getByRole('navigation', { name: 'Main navigation' })
  const composer = page
    .locator('[data-slot="composer-root"] [contenteditable="true"]')
    .filter({ visible: true })
    .first()
  await expect(rail).toBeVisible()
  await composer.fill('Keep this unsent message while I browse my skills.')
  const originalUrl = page.url()
  await page.screenshot({ path: test.info().outputPath('meu-home.png') })

  await rail.locator('[data-meu-nav="plugins"]').click()
  await expect(page.getByRole('heading', { name: 'Plugins', exact: true })).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Customize' })).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('meu-plugins.png') })
  await rail.locator('[data-meu-nav="skills"]').click()
  await expect(page.getByRole('heading', { name: 'Skills', exact: true })).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('meu-skills.png') })

  await rail.locator('[data-meu-nav="settings"]').click()
  await expect(page.locator('[data-overlay-surface]')).toBeVisible()
  await expect(rail).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('meu-settings.png') })
  await rail.locator('[data-meu-nav="scheduled"]').click()
  await expect(rail.locator('[data-meu-nav="scheduled"]')).toHaveAttribute('aria-current', 'page')
  await rail.locator('[data-meu-nav="home"]').click()
  await expect(page).toHaveURL(originalUrl)
  await expect(composer).toHaveText('Keep this unsent message while I browse my skills.')

  for (const width of [1024, 640, 400]) {
    await app.evaluate(({ BrowserWindow }, targetWidth) => {
      const window = BrowserWindow.getAllWindows()[0]!
      window.setMinimumSize(320, 400)
      window.setSize(targetWidth, 800)
    }, width)
    await expect(rail).toBeVisible()
    await rail.locator('[data-meu-nav="plugins"]').click()
    await expect(page.getByRole('heading', { name: 'Plugins', exact: true })).toBeVisible()
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.screenshot({ path: test.info().outputPath(`meu-plugins-${width}.png`) })
    await rail.locator('[data-meu-nav="home"]').click()
    await expect(composer).toHaveText('Keep this unsent message while I browse my skills.')
  }
  await app.evaluate(({ BrowserWindow }) => {
    BrowserWindow.getAllWindows()[0]!.setSize(1220, 800)
  })
  const receipt = await runDesktopChatSmoke(page, {
    mockUrl: fixture.mockUrl,
    phase: 'new',
    outDir: test.info().outputPath('chat')
  })
  const conversationUrl = page.url()
  await rail.locator('[data-meu-nav="plugins"]').click()
  await expect(page.getByRole('heading', { name: 'Plugins', exact: true })).toBeVisible()
  await rail.locator('[data-meu-nav="home"]').click()
  await expect(page).toHaveURL(conversationUrl)
  await expect(page.locator('[data-slot="aui_thread-viewport"]').filter({ visible: true }).first()).toContainText(
    receipt.transcript.user.text
  )
  await expect(page.locator('[data-slot="aui_thread-viewport"]').filter({ visible: true }).first()).toContainText(
    receipt.transcript.assistant.text
  )
  await rail.locator('[data-meu-nav="settings"]').click()
  await page.locator('[data-tour="nav-config:appearance"]').click()
  await page.locator('[data-tour="nav-config:appearance:theme"]').click()
  await page.getByRole('button', { name: 'Dark', exact: true }).click()
  await expect(page.locator('html')).toHaveAttribute('data-hermes-mode', 'dark')
  await rail.locator('[data-meu-nav="home"]').click()
  await page.screenshot({ path: test.info().outputPath('meu-home-dark.png') })
})
