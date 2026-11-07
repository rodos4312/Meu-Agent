import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

import yaml from 'js-yaml'

import { buildAppEnv, launchDesktop, type MockBackendFixture, setupMockBackend, waitForAppReady } from './fixtures'
import { expect, test } from './test'

let fixture: MockBackendFixture

test.beforeAll(async () => {
  fixture = await setupMockBackend()
})

test('native Coordinator status shows acceptance and version-bound review after reload', async () => {
  test.setTimeout(180_000)
  const own = await setupMockBackend({ extraConfig: '\ndelegation:\n  backend: meu_coordinator\n' })
  try {
    await waitForAppReady(own, 90_000)
    const root = path.join(own.sandbox.root, 'coordinator-project')
    fs.mkdirSync(root)
    const python = process.env.HERMES_DESKTOP_PYTHON
    if (!python) throw new Error('Set HERMES_DESKTOP_PYTHON to the isolated test interpreter.')
    const seed = spawnSync(
      python,
      [
        '-c',
        [
          'import sys,json,hashlib',
          'from pathlib import Path',
          'from hermes_constants import get_hermes_home',
          'from plugins.delegation.meu_coordinator.projects import new_project',
          'root=Path(sys.argv[1]); (root/"answer.txt").write_text("three tasks",encoding="utf-8")',
          'def task(id,**kw): return dict(id=id,goal="Review imports" if id=="review" else "Build task list",workload="complex",acceptance="Import the same file twice; exactly three tasks remain.",parallel_safe=False,write_paths=["answer.txt"] if id=="build" else [],**kw)',
          'r=new_project("progress-rehearsal",str(root),[task("build"),task("review",depends_on=["build"],review_of="build")])',
          'built=r["tasks"]["build"]; built.update(state="verified",attempt=1,evidence="Reload restored three tasks.",artifacts={"answer.txt":hashlib.sha256(b"three tasks").hexdigest()})',
          'r["tasks"]["review"].update(state="needs_review",attempt=1,reviewed_attempt=1,reviewed_artifacts=built["artifacts"],result={"model":"fixture-review-model","schema_valid":True,"summary":json.dumps({"verdict":"pass","check":"Import twice","observed":"Exactly three tasks remained."})})',
          'd=get_hermes_home()/"coordinator"; d.mkdir(exist_ok=True); (d/"progress-rehearsal.json").write_text(json.dumps(r),encoding="utf-8")'
        ].join('\n'),
        root
      ],
      { cwd: path.resolve(import.meta.dirname, '../../..'), env: buildAppEnv(own.sandbox), encoding: 'utf8' }
    )
    expect(seed.status, seed.stderr).toBe(0)
    const composer = own.page
      .locator('[data-slot="composer-root"] [contenteditable="true"]')
      .filter({ visible: true })
      .first()
    await composer.fill(
      'E2E_CALL(tool_call)[{"calls":[{"name":"coordinate_project","arguments":{"action":"status","project":"progress-rehearsal"}}]}]'
    )
    await composer.press('Enter')
    const card = own.page.locator('[data-slot="project-progress"]')
    await expect(card).toContainText('1/2 verified', { timeout: 60_000 })
    await card.locator('summary').first().click()
    await expect(card).toContainText('Import the same file twice; exactly three tasks remain.')
    await expect(card).toContainText('Awaiting verification')
    await expect(card).toContainText('Review result · Pass reported')
    await expect(card).toContainText('fixture-review-model')
    await card.screenshot({ path: test.info().outputPath('meu-coordinator-progress.png') })
    await own.page.reload()
    await waitForAppReady(own, 90_000)
    await expect(card).toContainText('1/2 verified', { timeout: 45_000 })
    await card.locator('summary').first().click()
    await expect(card).toContainText('Exactly three tasks remained.')
    await expect(card).toContainText('Awaiting verification')
    await card.screenshot({ path: test.info().outputPath('meu-coordinator-progress-restored.png') })
  } finally {
    await own.cleanup()
  }
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
