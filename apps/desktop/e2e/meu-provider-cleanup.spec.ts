import { type MockBackendFixture, setupMockBackend, waitForAppReady } from './fixtures'
import { expect, test } from './test'

let fixture: MockBackendFixture

test.beforeAll(async () => {
  fixture = await setupMockBackend()
})

test.afterAll(async () => {
  await fixture?.cleanup()
})

test('retired billing links open usable provider keys and no Nous account surface remains', async () => {
  test.setTimeout(180_000)
  const { page } = fixture
  await waitForAppReady(fixture, 90_000)
  const composer = page
    .locator('[data-slot="composer-root"] [contenteditable="true"]')
    .filter({ visible: true })
    .first()
  await composer.fill('Keep this draft while I configure my provider.')
  await page.evaluate(() => {
    window.location.hash = '#/settings?tab=billing'
  })
  await expect(page).toHaveURL(/tab=providers.*pview=keys/)
  await expect(page.getByRole('button', { name: 'Billing', exact: true })).toHaveCount(0)
  await expect(page.getByText('Connect your Nous account', { exact: true })).toHaveCount(0)
  await expect(page.getByText('DeepSeek', { exact: true })).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('meu-provider-keys.png') })

  await page.evaluate(() => {
    window.location.hash = '#/settings?tab=providers&pview=accounts'
  })
  await expect(page.getByRole('button', { name: 'Have an API key instead?', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Other providers', exact: true }).click()
  await expect(page.getByText('ChatGPT or Codex Subscription', { exact: true })).toBeVisible()
  await expect(page.getByText('Nous Portal', { exact: true })).toHaveCount(0)
  await page.screenshot({ path: test.info().outputPath('meu-provider-accounts.png') })
  await page.getByRole('navigation', { name: 'Main navigation' }).locator('[data-meu-nav="home"]').click()
  await expect(composer).toHaveText('Keep this draft while I configure my provider.')
})
