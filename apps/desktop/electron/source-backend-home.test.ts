import { execFile } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { promisify } from 'node:util'

import { expect, it } from 'vitest'

import { resolveSourceInstallationBackend } from './source-backend'

it('probes and returns the selected data home instead of borrowing the launcher parent home', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'meu-source-home-'))
  const home = path.join(root, 'selected home')
  const receipt = path.join(root, 'probe.json')
  const script = path.join(root, 'probe.cjs')
  const launcher = path.join(root, '.hermes', 'bin', process.platform === 'win32' ? 'hermes.cmd' : 'hermes')

  try {
    fs.mkdirSync(path.dirname(launcher), { recursive: true })
    fs.mkdirSync(path.join(root, 'hermes_cli'))
    fs.writeFileSync(path.join(root, 'hermes_cli', 'main.py'), '# fixture')
    fs.writeFileSync(script, `require('node:fs').writeFileSync(${JSON.stringify(receipt)}, JSON.stringify({home:process.env.HERMES_HOME})); if(process.env.HERMES_HOME !== ${JSON.stringify(home)}) process.exit(23)`)
    fs.writeFileSync(launcher, process.platform === 'win32'
      ? `@"${process.execPath}" "${script}" %*\r\n`
      : `#!/bin/sh\nexec "${process.execPath}" "${script}" "$@"\n`, { mode: 0o755 })

    const backend = await resolveSourceInstallationBackend(root, ['gateway', 'ensure'], {
      hermesHome: home, env: { ...process.env, HERMES_HOME: path.join(root, 'foreign home') }
    })

    expect(backend).not.toBeNull()
    expect(JSON.parse(fs.readFileSync(receipt, 'utf8'))).toEqual({ home })
    await promisify(execFile)(backend!.command, backend!.args, {
      env: { ...process.env, HERMES_HOME: path.join(root, 'foreign home'), ...backend!.env },
      shell: backend!.shell, windowsHide: true
    })
    expect(JSON.parse(fs.readFileSync(receipt, 'utf8'))).toEqual({ home })
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})
