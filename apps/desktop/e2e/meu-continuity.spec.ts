import path from 'node:path'
import { DatabaseSync } from 'node:sqlite'

import { buildAppEnv, launchDesktop, setupMockBackend, waitForAppReady } from './fixtures'
import { expect, test } from './test'

const prompt = 'MEU_CONTINUITY_ACTIVE'
const answer = 'MEU_CONTINUITY_REPLY the full answer survived the disconnected viewer.'
const draft = 'Unsent follow-up remains in this same conversation.'
const composer = (page: Awaited<ReturnType<typeof launchDesktop>>['page']) =>
  page.locator('[data-slot="composer-root"] [contenteditable="true"]').filter({ visible: true }).first()

function storedTurns(home: string) {
  const db = new DatabaseSync(path.join(home, 'state.db'), { readOnly: true })
  try {
    return db.prepare("SELECT session_id FROM messages WHERE role='user' AND content=?").all(prompt)
  } finally {
    db.close()
  }
}

for (const fault of ['socket loss', 'app restart'] as const) {
  test(`the same conversation, draft and single admitted turn survive ${fault}`, async () => {
    test.setTimeout(180_000)
    const fixture = await setupMockBackend({
      mockServer: {
        holdFirstStreamForPrompt: prompt,
        replyForPrompt: () => answer
      }
    })
    let reopened: Awaited<ReturnType<typeof launchDesktop>> | undefined
    let drop: (() => void) | undefined
    let sockets = 0
    try {
      if (fault === 'socket loss') {
        await fixture.page.routeWebSocket(/\/api\/ws/, socket => {
          const server = socket.connectToServer()
          sockets += 1
          socket.onMessage(raw => {
            const frame = JSON.parse(String(raw))
            if (frame.method === 'prompt.submit') {
              drop = () => socket.close({ code: 1012, reason: 'Continuity test disconnect' })
            }
            server.send(raw)
          })
        })
        await fixture.page.reload()
      }
      await waitForAppReady(fixture, 90_000)
      await composer(fixture.page).fill(prompt)
      await composer(fixture.page).press('Enter')
      await fixture.mock.waitForHeldStream()
      await expect(fixture.page.locator('[data-slot="aui_thread-viewport"]').first()).toContainText(
        'MEU_CONTINUITY_REPLY'
      )
      const route = fixture.page.url()
      await composer(fixture.page).fill(draft)
      if (fault === 'socket loss') {
        const before = sockets
        expect(drop).toBeDefined()
        drop!()
        fixture.mock.releaseHeldStream()
        await expect.poll(() => sockets, { timeout: 45_000 }).toBeGreaterThan(before)
      } else {
        await fixture.app.close()
        fixture.mock.releaseHeldStream()
        reopened = await launchDesktop(buildAppEnv(fixture.sandbox))
        await waitForAppReady({ ...fixture, ...reopened }, 90_000)
      }
      const page = reopened?.page ?? fixture.page
      await expect(page).toHaveURL(route, { timeout: 45_000 })
      await expect(page.locator('[data-slot="aui_thread-viewport"]').first()).toContainText(answer, { timeout: 45_000 })
      await expect(composer(page)).toHaveText(draft)
      await expect(page.locator('[data-slot="composer-root"] button[aria-label="Stop"]')).toHaveCount(0)
      await expect.poll(() => storedTurns(fixture.sandbox.hermesHome).length).toBe(1)
      expect(fixture.mock.receivedPrompts.filter(text => text === prompt)).toHaveLength(1)
      await page.screenshot({ path: test.info().outputPath(`meu-continuity-${fault.replace(' ', '-')}.png`) })
    } finally {
      fixture.mock.releaseHeldStream()
      await reopened?.app.close()
      await fixture.cleanup()
    }
  })
}
