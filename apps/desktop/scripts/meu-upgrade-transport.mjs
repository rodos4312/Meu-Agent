// Test transport only. The real updater, signature checks, IPC and installer remain intact.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { createHash } from 'node:crypto'
import signing from '../meu-release-signing.cjs'

export function verifiedMeuCandidate(directory, publicKey) {
  const release = JSON.parse(fs.readFileSync(path.join(directory, 'meu-release.json'), 'utf8'))
  signing.verifyRelease(release, publicKey)
  assert.equal(release.repository, 'rodos4312/Meu-Agent')
  assert.equal(release.branch, 'dev/meu-foundation')
  assert.equal(release.channel, 'meu-preview')
  assert.equal(release.file, `Meu-${release.version}-win-x64.exe`)
  const bytes = fs.readFileSync(path.join(directory, release.file))
  assert.equal(bytes.length, release.size)
  assert.equal(createHash('sha256').update(bytes).digest('hex'), release.sha256)
  assert.equal(createHash('sha512').update(bytes).digest('base64'), release.sha512)
  return release
}

export async function installMeuUpgradeTransport(app, input) {
  await app.evaluate(({ session, BrowserWindow }, input) => {
    const fs = process.getBuiltinModule('fs')
    const path = process.getBuiltinModule('path')
    const { Readable, Transform } = process.getBuiltinModule('stream')
    const { release, directory, baseline, baselineDirectory, failOnRestart } = input
    const base = `https://github.com/rodos4312/Meu-Agent/releases/download/meu-v${release.version}/`
    const list = 'https://api.github.com/repos/rodos4312/Meu-Agent/releases?per_page=50'
    const entry = value => ({
      draft: false,
      tag_name: `meu-v${value.version}`,
      assets: ['meu-release.json', 'meu-preview.yml', value.file].map(name => ({
        name,
        size: name === value.file ? value.size : 1,
        browser_download_url: `https://github.com/rodos4312/Meu-Agent/releases/download/meu-v${value.version}/${name}`
      }))
    })
    const state = { mode: input.mode ?? 'forged', requests: [] }
    globalThis.meuNativeRehearsal = state
    const original = globalThis.fetch
    globalThis.fetch = async (url, options) => {
      const key = String(url)
      if (key === list) return new Response(JSON.stringify([entry(release)]))
      if (key === base + 'meu-release.json') {
        return new Response(
          JSON.stringify(
            state.mode === 'forged' ? { ...release, signature: Buffer.alloc(64).toString('base64') } : release
          )
        )
      }
      if (baseline) {
        const oldBase = `https://github.com/rodos4312/Meu-Agent/releases/download/meu-v${baseline.version}/`
        if (key === `https://api.github.com/repos/rodos4312/Meu-Agent/releases/tags/meu-v${baseline.version}`)
          return new Response(JSON.stringify(entry(baseline)))
        if (key === oldBase + 'meu-release.json') return new Response(JSON.stringify(baseline))
        if (key === oldBase + baseline.file)
          return new Response(Readable.toWeb(fs.createReadStream(path.join(baselineDirectory, baseline.file))))
      }
      return original(url, options)
    }
    session.fromPartition('electron-updater', { cache: false }).protocol.handle('https', request => {
      const url = new URL(request.url)
      const canonical = url.origin + url.pathname
      state.requests.push(canonical)
      if (canonical === base + 'meu-preview.yml')
        return new Response(fs.readFileSync(path.join(directory, 'meu-preview.yml')), {
          headers: { 'content-type': 'text/yaml' }
        })
      if (canonical !== base + release.file) throw new Error('Unexpected native upgrade destination: ' + canonical)
      let first = true
      const stream = fs.createReadStream(path.join(directory, release.file)).pipe(
        new Transform({
          transform(chunk, _encoding, done) {
            if (first && state.mode === 'tampered') chunk[0] ^= 1
            first = false
            done(null, chunk)
          }
        })
      )
      return new Response(Readable.toWeb(stream), {
        headers: { 'content-type': 'application/octet-stream', 'content-length': String(release.size) }
      })
    })
    if (failOnRestart) {
      const contents = BrowserWindow.getAllWindows()[0].webContents
      const send = contents.send.bind(contents)
      contents.send = (channel, payload, ...args) => {
        if (channel === 'hermes:updates:progress' && payload?.stage === 'restart') {
          if (input.migrationPython) {
            const { execFileSync } = process.getBuiltinModule('child_process')
            execFileSync(
              input.migrationPython,
              [
                '-I',
                '-c',
                'import os,sqlite3;from pathlib import Path;p=Path(os.environ["MEU_HOME"]);' +
                  'db=sqlite3.connect(p/"state.db");db.execute("ALTER TABLE messages ADD COLUMN meu_failed_version TEXT");db.close();' +
                  'f=p/"config.yaml";f.write_text(f.read_text(encoding="utf-8")+"meu_failed_update: true\\n",encoding="utf-8")'
              ],
              { windowsHide: true, timeout: 30_000 }
            )
          }
          // The unpublished next-version build owns its startup-failure seam;
          // the real Windows shell relaunch does not need environment injection.
        }
        return send(channel, payload, ...args)
      }
    }
  }, input)
}
