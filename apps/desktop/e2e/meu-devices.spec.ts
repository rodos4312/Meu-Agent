import { type MockBackendFixture, setupMockBackend, waitForAppReady } from './fixtures'
import { expect, test } from './test'

let fixture: MockBackendFixture
test.beforeAll(async () => {
  fixture = await setupMockBackend()
})
test.afterAll(async () => {
  await fixture?.cleanup()
})

test('device settings expose one management flow and retain the composer', async () => {
  test.setTimeout(180_000)
  const { app, page } = fixture
  await waitForAppReady(fixture, 90_000)
  const composer = page
    .locator('[data-slot="composer-root"] [contenteditable="true"]')
    .filter({ visible: true })
    .first()
  await composer.fill('Keep this draft while I manage my devices.')
  await page.evaluate(() => {
    window.location.hash = '#/settings?tab=gateway'
  })
  await expect(page.getByRole('heading', { name: 'Devices and sharing', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Add device · show QR' })).toBeVisible()
  await expect(page.getByRole('checkbox', { name: 'This is my device · PC owner' })).not.toBeChecked()
  await expect(page.getByRole('button', { name: 'Show pairing code', exact: true })).toHaveCount(0)
  await page.screenshot({ path: test.info().outputPath('meu-devices.png') })
  await app.evaluate(({ BrowserWindow }) => {
    BrowserWindow.getAllWindows()[0]!.setSize(720, 800)
  })
  await expect(page.getByRole('heading', { name: 'Devices and sharing', exact: true })).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('meu-devices-compact.png') })
  await page.getByRole('navigation', { name: 'Main navigation' }).locator('[data-meu-nav="home"]').click()
  await expect(composer).toHaveText('Keep this draft while I manage my devices.')
})
