import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

import type { Page } from '@playwright/test'

import { buildAppEnv, launchDesktop, setupMockBackend, waitForAppReady } from './fixtures'
import { expect, test } from './test'

async function openProjectNotes(page: Page) {
  const notes = page.getByRole('button', { name: 'Project notes', exact: true })

  if (!(await notes.isVisible())) {
    await page.getByRole('button', { name: 'Open Memory rehearsal', exact: true }).click()
  }

  await notes.click()

  return page.getByRole('dialog')
}

test('project notes use real local files and survive a desktop restart', async () => {
  test.setTimeout(180_000)
  const fixture = await setupMockBackend()
  const { sandbox } = fixture
  let reopened: Awaited<ReturnType<typeof launchDesktop>> | undefined

  try {
    await waitForAppReady(fixture, 90_000)
    const root = path.join(sandbox.root, 'birthday-project')
    fs.mkdirSync(root)
    const python = process.env.HERMES_DESKTOP_PYTHON

    if (!python) {
      throw new Error('Set HERMES_DESKTOP_PYTHON to the isolated test interpreter.')
    }

    const seed = spawnSync(
      python,
      [
        '-c',
        [
          'import sys',
          'from hermes_cli.projects_db import connect_closing, create_project',
          'from tools.memory_tool import load_on_disk_store',
          'with connect_closing() as conn: create_project(conn, name="Memory rehearsal", folders=[sys.argv[1]])',
          's=load_on_disk_store(project_cwd=sys.argv[1])',
          'assert s.add("project", "Export PNG in A5.")["success"]'
        ].join('\n'),
        root
      ],
      { cwd: path.resolve(import.meta.dirname, '../../..'), env: buildAppEnv(sandbox), encoding: 'utf8' }
    )

    expect(seed.status, seed.stderr).toBe(0)
    await fixture.page.evaluate(() => localStorage.setItem('hermes.desktop.agentsGroupedByWorkspace', 'true'))
    await fixture.page.reload()
    await waitForAppReady(fixture, 90_000)
    const dialog = await openProjectNotes(fixture.page)
    await expect(dialog.getByText('Export PNG in A5.', { exact: true })).toBeVisible()
    await dialog.getByRole('button', { name: 'Edit note', exact: true }).click()
    await dialog.getByRole('textbox', { name: 'Note', exact: true }).fill('Export PNG in A4.')
    await dialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog.getByRole('status')).toContainText('Saved. New conversations')
    await expect(dialog.getByRole('listitem').getByText('Export PNG in A4.', { exact: true })).toBeVisible()

    const file = await dialog
      .locator('p')
      .filter({ hasText: /PROJECT\.md$/ })
      .innerText()

    const relative = path.relative(sandbox.hermesHome, file)
    expect(path.isAbsolute(relative)).toBe(false)
    expect(relative).not.toMatch(/^\.\./)
    expect(fs.readFileSync(file, 'utf8')).toContain('Export PNG in A4.')
    await fixture.page.screenshot({ path: test.info().outputPath('meu-project-notes.png') })
    await fixture.app.close()
    reopened = await launchDesktop(buildAppEnv(sandbox))
    await waitForAppReady({ ...fixture, ...reopened }, 90_000)
    const restored = await openProjectNotes(reopened.page)
    await expect(restored.getByText('Export PNG in A4.', { exact: true })).toBeVisible()
    await restored.getByRole('button', { name: 'Delete note', exact: true }).click()
    await expect(restored.getByText('No saved notes for this project yet.')).toBeVisible()
    expect(fs.readFileSync(file, 'utf8')).not.toContain('Export PNG in A4.')
    await reopened.page.screenshot({ path: test.info().outputPath('meu-project-notes-reopened.png') })
  } finally {
    await reopened?.app.close()
    await fixture.cleanup()
  }
})
