import { type MockBackendFixture, setupMockBackend, waitForAppReady } from './fixtures'
import { expect, test } from './test'

let fixture: MockBackendFixture
test.beforeAll(async () => {
  fixture = await setupMockBackend()
})
test.afterAll(async () => {
  await fixture?.cleanup()
})

test('Meu offers an update, preserves the draft when postponed and installs only after an explicit choice', async () => {
  test.setTimeout(180_000)
  const { app, page } = fixture
  await waitForAppReady(fixture, 90_000)
  await page.route('https://api.github.com/repos/rodos4312/Meu-Agent/**', route =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ body: '- Update checks and notifications' })
    })
  )
  await app.evaluate(({ ipcMain }) => {
    const record = { checks: 0, applies: 0 }
    ;(globalThis as unknown as { meuUpdateRehearsal: typeof record }).meuUpdateRehearsal = record
    ipcMain.removeHandler('hermes:updates:check')
    ipcMain.handle('hermes:updates:check', () => {
      record.checks++
      return {
        supported: true,
        mechanism: 'electron-updater',
        channel: 'meu-preview',
        updateAvailable: true,
        currentVersion: '0.1.0-dev.8',
        latestTag: 'meu-v0.1.0-dev.9',
        targetSha: 'a'.repeat(40),
        fetchedAt: Date.now()
      }
    })
    ipcMain.removeHandler('hermes:updates:apply')
    ipcMain.handle('hermes:updates:apply', () => {
      record.applies++
      // UI rehearsal only: no real installer or backend stop.
      return { ok: true, handedOff: true, mechanism: 'electron-updater' }
    })
  })
  const counts = () =>
    app.evaluate(
      () =>
        (
          globalThis as unknown as {
            meuUpdateRehearsal: { checks: number; applies: number }
          }
        ).meuUpdateRehearsal
    )
  const composer = page
    .locator('[data-slot="composer-root"] [contenteditable="true"]')
    .filter({ visible: true })
    .first()
  await composer.fill('Keep my draft while I check updates.')
  const openAbout = async () => {
    await page.getByRole('navigation', { name: 'Main navigation' }).locator('[data-meu-nav="settings"]').click()
    await page.getByRole('button', { name: 'About', exact: true }).click()
  }
  await openAbout()
  await page.getByRole('button', { name: 'Check now', exact: true }).click()
  const notification = page.getByRole('status').filter({ hasText: 'Update ready' })
  await expect(notification).toBeVisible()
  expect((await counts()).applies).toBe(0)
  await page.screenshot({ path: test.info().outputPath('meu-update-notification.png') })
  await notification.getByRole('button', { name: "See what's new", exact: true }).click()
  const dialog = page.getByRole('dialog').filter({ has: page.getByRole('button', { name: 'Update now', exact: true }) })
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText('Update checks and notifications')
  expect((await counts()).applies).toBe(0)
  await page.screenshot({ path: test.info().outputPath('meu-update-choice.png') })
  await dialog.getByRole('button', { name: 'Maybe later', exact: true }).click()
  expect((await counts()).applies).toBe(0)
  await page.getByRole('navigation', { name: 'Main navigation' }).locator('[data-meu-nav="home"]').click()
  await expect(composer).toHaveText('Keep my draft while I check updates.')
  await openAbout()
  await page.getByRole('button', { name: 'Update now', exact: true }).click()
  await expect.poll(async () => (await counts()).applies).toBe(1)
})
