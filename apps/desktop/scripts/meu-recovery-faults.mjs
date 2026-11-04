// Private Windows fault scenarios; every process target has an owned image/time.
import assert from 'node:assert/strict'
import { execFileSync, spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { expect } from '@playwright/test'

export function recoveryFault(scenario, { python, env }) {
  assert(['startup-failure', 'guardian-loss', 'locked-package', 'interrupted-install'].includes(scenario))
  const control = path.join(import.meta.dirname, 'meu-recovery-control.py')
  const request = path.join(env.TEMP, 'meu-native-interrupt.request')
  const ready = path.join(env.TEMP, 'meu-native-interrupt.ready')
  const interrupted = scenario === 'interrupted-install'
  let locker
  let resumed
  if (interrupted) {
    assert(!fs.existsSync(request) && !fs.existsSync(ready), 'Fault markers must be fresh')
    fs.writeFileSync(request, 'Disposable Meu interruption rehearsal', { flag: 'wx' })
  }
  const run = (...args) => execFileSync(python, ['-I', control, ...args], { env, windowsHide: true, timeout: 30_000 })
  const exit = child => new Promise((resolve, reject) => {
    child.once('error', reject)
    child.once('exit', code => code === 0 ? resolve() : reject(new Error(`Retained recovery exited with ${code}`)))
  })
  return {
    control: scenario === 'startup-failure' ? undefined : control,
    async afterHandoff(transaction, executable) {
      if (scenario === 'startup-failure') return false
      await expect.poll(transaction, { timeout: 30_000 }).not.toBeNull()
      const record = transaction()
      assert(fs.existsSync(path.join(record.location, 'resume.json')), 'Baseline must support durable recovery')
      if (interrupted) {
        await expect.poll(() => fs.existsSync(ready) && /^\d+$/.test(fs.readFileSync(ready, 'utf8').trim()),
          { timeout: 180_000 }).toBe(true)
        assert(fs.statSync(path.join(path.dirname(executable), 'resources/app.asar')).size < 1024)
        const installerPid = Number(fs.readFileSync(ready, 'utf8').trim())
        assert(Number.isSafeInteger(installerPid) && installerPid > 0)
        run('installer', record.location, String(installerPid))
      } else {
        await expect.poll(() => {
          const file = path.join(record.location, 'signal.json')
          return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')).state : undefined
        }, { timeout: 180_000 }).toBe('failed')
      }
      if (scenario === 'locked-package') {
        locker = spawn(python, ['-I', control, 'hold', path.join(path.dirname(executable), 'resources/app.asar')],
          { env, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] })
        await new Promise((resolve, reject) => {
          const timer = setTimeout(() => reject(new Error('Package locker did not become ready')), 30_000)
          const done = callback => value => { clearTimeout(timer); callback(value) }
          locker.once('error', done(reject))
          locker.stdout.once('data', done(bytes => bytes.toString().includes('LOCKED') ? resolve() : reject(new Error('Package locker failed'))))
          locker.once('exit', done(code => reject(new Error(`Package locker exited: ${code}`))))
        })
      }
      const fresh = Object.fromEntries(['SystemRoot', 'WINDIR', 'COMSPEC', 'LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'TEMP', 'TMP']
        .filter(key => env[key]).map(key => [key, env[key]]))
      fresh.PATH = path.join(env.SystemRoot, 'System32')
      resumed = spawn(path.join(record.location, 'runtime/pythonw.exe'), ['-I', '-S', '-m', 'meu_recovery_start'],
        { env: fresh, windowsHide: true, stdio: 'ignore' })
      this.resumed = exit(resumed)
      void this.resumed.catch(() => {})
      if (locker) {
        await expect.poll(() => transaction()?.state, { timeout: 180_000 }).toBe('waiting-for-files')
        assert.equal(locker.exitCode, null, 'Recovery must not terminate the foreign file holder')
        locker.stdin.end()
      }
      return false
    },
    dispose() {
      locker?.stdin.end()
      if (interrupted) for (const file of [request, ready]) {
        if (fs.existsSync(file)) fs.unlinkSync(file)
      }
    }
  }
}
