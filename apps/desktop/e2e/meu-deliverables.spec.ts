import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

import { buildAppEnv, setupMockBackend, waitForAppReady } from './fixtures'
import { expect, test } from './test'

function pdfFixture() {
  const content = 'BT /F1 24 Tf 50 700 Td (Meu PDF rehearsal) Tj ET\n'

  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${content.length} >>\nstream\n${content}endstream`
  ]

  let document = '%PDF-1.4\n'

  const offsets = objects.map((object, index) => {
    const offset = document.length
    document += `${index + 1} 0 obj\n${object}\nendobj\n`

    return offset
  })

  const xref = document.length
  document += `xref\n0 6\n0000000000 65535 f \n${offsets.map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`

  return document
}

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
    fs.writeFileSync(path.join(root, 'report.pdf'), pdfFixture())

    const html =
      '<!doctype html><html><head><title>Birthday card</title></head><body><h1>Happy birthday</h1><p>' +
      'A local document. '.repeat(12) +
      '</p><script>window.open("https://unexpected.invalid")</script></body></html>'

    const content =
      'MEDIA:' +
      path.join(root, 'report.txt') +
      '\nMEDIA:' +
      path.join(root, 'report.pdf') +
      '\n```html\n' +
      html +
      '\n```'

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
    await fixture.page.getByRole('button', { name: 'report.pdf', exact: true }).click()
    await expect(dialog.locator('iframe')).toHaveAttribute('src', /^blob:/)
    await expect(dialog.getByRole('alert')).toHaveCount(0)
    await expect
      .poll(
        async () => {
          const frames = fixture.page
            .frames()
            .filter(frame => frame.url().startsWith('blob:') || frame.url().startsWith('chrome-extension:'))

          for (const frame of frames) {
            const ready = await frame
              .evaluate(() => {
                const viewer = document.querySelector('pdf-viewer') as
                  (HTMLElement & { loaded?: Promise<unknown> }) | null

                return Boolean(viewer || document.querySelector('embed'))
              })
              .catch(() => false)

            if (ready) {
              return true
            }
          }

          return false
        },
        { timeout: 15_000 }
      )
      .toBe(true)
    await fixture.page.screenshot({ path: test.info().outputPath('meu-pdf-preview.png') })
    await fixture.page.keyboard.press('Escape')
    await expect(fixture.page.getByRole('button', { name: 'report.txt', exact: true })).toBeVisible()
    await fixture.page.screenshot({ path: test.info().outputPath('meu-unified-deliverables.png') })
  } finally {
    await fixture.cleanup()
  }
})
