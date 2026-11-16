import { expect, test } from 'vitest'

import { bootstrapSnapshot, readCanonicalInstallStamp } from './bootstrap-state'
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { type InstallStamp } from './install-stamp'

function stamp(payload: InstallStamp['payload']): InstallStamp {
  return {
    schemaVersion: 2,
    commit: null,
    commitDate: null,
    branch: null,
    builtAt: null,
    dirty: false,
    source: 'build',
    distribution: 'desktop-app',
    updateMechanism: 'self',
    baseVersion: null,
    displayVersion: null,
    distance: null,
    payload,
    tag: null
  }
}

test.each(['bundled', 'bootstrap', 'light'] as const)(
  'bootstrap state retains the %s artifact fact across failure and reset',
  payload => {
    const artifact = stamp(payload)
    const state = { error: 'backend exited before setup', setupChoice: null }
    expect(bootstrapSnapshot(state, artifact)).toEqual({ ...state, bundled: payload === 'bundled' })
    expect(bootstrapSnapshot({ error: null, setupChoice: null }, artifact).bundled).toBe(payload === 'bundled')
    expect(state).not.toHaveProperty('bundled')
    expect(bootstrapSnapshot(state, null).bundled).toBe(false)
    expect(bootstrapSnapshot({ ...state, bundled: payload !== 'bundled' }, artifact).bundled).toBe(
      payload === 'bundled'
    )
  }
)


test('canonical runtime provenance is read without manufacturing a fallback identity', () => {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'meu-runtime-stamp-'))
  try {
    expect(readCanonicalInstallStamp(root)).toBeNull()
    const file=path.join(root,'install-stamp.json')
    fs.writeFileSync(file,'invalid json')
    expect(readCanonicalInstallStamp(root)).toBeNull()
    const value={source:'ci',commit:'a'.repeat(40),payload:'bootstrap',sourceSeed:{sha256:'b'.repeat(64)}}
    fs.writeFileSync(file,JSON.stringify(value))
    expect(readCanonicalInstallStamp(root)).toEqual(value)
  } finally {fs.rmSync(root,{recursive:true,force:true})}
})
