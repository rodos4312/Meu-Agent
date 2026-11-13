import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { afterEach, expect, it } from 'vitest'

import { readDesktopUpdateBranch, readMeuChannelPreference, writeMeuChannelPreference } from './desktop-update-config'
import { meuChannelPreference } from './updater/meu-channel'

const roots: string[] = []
const settings = (content?: string) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'meu-update-config-'))
  roots.push(root)
  const file = path.join(root, 'updates.json')
  if (content !== undefined) {
    fs.writeFileSync(file, content)
  }

  return file
}

afterEach(() => {
  for (const root of roots.splice(0)) {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

it('migrates an existing settings file without a channel to stable', () => {
  const file = settings(JSON.stringify({ branch: 'main' }))
  expect(meuChannelPreference(readMeuChannelPreference(file), 'stable')).toBe('stable')
  expect(readDesktopUpdateBranch(file, 'main')).toEqual({ branch: 'main', branchExplicit: true })
})

it.each([undefined, '', '{not json', '[]', 'null'])('a missing or unreadable file (%j) is the stable default', content => {
  const file = settings(content)
  expect(meuChannelPreference(readMeuChannelPreference(file), 'stable')).toBe('stable')
  expect(readDesktopUpdateBranch(file, 'main')).toEqual({ branch: 'main', branchExplicit: false })
})

it('saves the channel atomically and keeps every other key', () => {
  const file = settings(JSON.stringify({ branch: 'feature/x', other: 1 }))
  writeMeuChannelPreference(file, 'rc')
  expect(JSON.parse(fs.readFileSync(file, 'utf8'))).toEqual({ branch: 'feature/x', other: 1, channel: 'rc' })
  expect(fs.existsSync(`${file}.tmp`)).toBe(false)
  writeMeuChannelPreference(file, 'stable')
  expect(readMeuChannelPreference(file)).toBe('stable')
})
