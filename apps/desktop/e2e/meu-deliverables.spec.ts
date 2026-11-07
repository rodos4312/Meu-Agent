import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

import { buildAppEnv, setupMockBackend, waitForAppReady } from './fixtures'
import { expect, test } from './test'

test('unified deliverables preview real session files and generated documents without leaving the catalog', async () => {
  test.setTimeout(180_000)
  const fixture = await setupMockBackend()
  const unexpectedRequests: string[] = []
  fixture.page.on('request', request => {
    if (request.url().includes('unexpected.invalid')) {
      unexpectedRequests.push(request.url())
    }
  })

  try {
    await waitForAppReady(fixture, 90_000)
    const root = path.join(fixture.sandbox.root, 'deliverables')
    fs.mkdirSync(root)
    fs.writeFileSync(path.join(root, 'report.txt'), 'Real delivered file — Ελληνικά\nSaved on this gateway.\n')

    const html =
      '<!doctype html><html><head><title>Birthday card</title></head><body><h1>Happy birthday</h1><p>' +
      'A local document. '.repeat(12) +
      '</p><script>window.open("https://unexpected.invalid")</script></body></html>'

    const content = 'MEDIA:' + path.join(root, 'report.txt') + '\n```html\n' + html + '\n```'
    const python = process.env.HERMES_DESKTOP_PYTHON

    if (!python) {
      throw new Error('Set the isolated test interpreter.')
    }

    const seeded = spawnSync(
      python,
      [
        '-c',
        [
          'import sys',
          'from hermes_state import SessionDB',
          'db=SessionDB()',
          "db.create_session('deliverables-rehearsal',source='cli',cwd=sys.argv[1])",
          "db.append_message('deliverables-rehearsal',role='user',content='Create my deliverables')",
          "db.append_message('deliverables-rehearsal',role='assistant',content=sys.argv[2])",
          'db.close()'
        ].join('\n'),
        root,
        content
      ],
      { cwd: path.resolve(import.meta.dirname, '../../..'), env: buildAppEnv(fixture.sandbox), encoding: 'utf8' }
    )

    expect(seeded.status, seeded.stderr).toBe(0)
    await fixture.page.reload()
    await waitForAppReady(fixture, 90_000)
    await fixture.page.getByRole('button', { name: 'Artifacts', exact: true }).click()
    await fixture.page.getByRole('button', { name: 'report.txt', exact: true }).click()
    const dialog = fixture.page.getByRole('dialog')
    await expect(dialog).toContainText('Real delivered file')
    await expect(dialog.getByRole('button', { name: 'Download', exact: true })).toBeEnabled()
    await fixture.page.screenshot({ path: test.info().outputPath('meu-delivered-file-preview.png') })
    await fixture.page.keyboard.press('Escape')
    await fixture.page.getByRole('button', { name: /Birthday.*\.html/i }).click()
    await expect(dialog.locator('iframe')).toHaveAttribute('sandbox', '')
    await expect(dialog.frameLocator('iframe').getByRole('heading', { name: 'Happy birthday' })).toBeVisible()
    expect((await dialog.locator('iframe').boundingBox())!.height).toBeGreaterThan(350)
    expect(unexpectedRequests).toEqual([])
    await fixture.page.screenshot({ path: test.info().outputPath('meu-generated-document-preview.png') })
    await fixture.page.keyboard.press('Escape')
    await expect(fixture.page.getByRole('button', { name: 'report.txt', exact: true })).toBeVisible()
    await fixture.page.screenshot({ path: test.info().outputPath('meu-unified-deliverables.png') })
  } finally {
    await fixture.cleanup()
  }
})
