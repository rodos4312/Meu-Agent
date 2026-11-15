import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { execFileSync } from 'node:child_process'
import { pathToFileURL } from 'node:url'

export function validateRcStamp(stamp, expected) {
  assert.equal(stamp.commit, expected)
  assert.equal(stamp.dirty, false)
  assert.equal(stamp.payload, 'bundled')
  assert.equal(stamp.branch, 'rc/meu-independence-rc1')
  assert.equal(stamp.meuUpdates.repository, 'rodos4312/Meu-Agent-RC-private')
  assert.equal(stamp.meuUpdates.channel, 'meu-rc')
  assert.equal(stamp.meuUpdates.branch, stamp.branch)
  assert.ok(stamp.runtime.repoDir && stamp.runtime.commands.hermes)
}

async function main() {
  const [executable, scratch, commit] = process.argv.slice(2)
  assert.equal(process.env.GITHUB_ACTIONS, 'true', 'Disposable CI only')
  const resources = path.join(path.dirname(executable), 'resources')
  const stamp = JSON.parse(fs.readFileSync(path.join(resources, 'install-stamp.json'), 'utf8'))
  validateRcStamp(stamp, commit)
  const payload = path.join(resources, 'agent-payload')
  const embedded = JSON.parse(fs.readFileSync(path.join(payload, stamp.runtime.repoDir, 'install-stamp.json'), 'utf8'))
  validateRcStamp(embedded, commit)
  assert.ok(fs.existsSync(path.join(resources, 'open-source-notices/Hermes-LICENSE.txt')))
  fs.mkdirSync(scratch, {recursive:true})
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
    !/(?:API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIALS|PRIVATE_KEY)$/.test(key) &&
    !['PYTHONHOME','PYTHONPATH','VIRTUAL_ENV','HERMES_RUNTIME_DIR','ELECTRON_RUN_AS_NODE','HERMES_DESKTOP_DEV_SERVER','HERMES_DESKTOP_HERMES','HERMES_DESKTOP_HERMES_ROOT','HERMES_DESKTOP_PYTHON'].includes(key)))
  Object.assign(env, {MEU_HOME:path.join(scratch,'profile'),HERMES_HOME:path.join(scratch,'profile'),
    HERMES_DESKTOP_USER_DATA_DIR:path.join(scratch,'desktop'),HERMES_DESKTOP_SKIP_PROTOCOL_REGISTRATION:'1',
    HERMES_DESKTOP_SKIP_QUIT_CONFIRM:'1',MEU_AGENT_MODE:'1',PYTHONUTF8:'1'})
  const cli = path.join(payload, stamp.runtime.commands.hermes)
  const run = args => execFileSync(cli,args,{env,cwd:scratch,encoding:'utf8',timeout:180000,windowsHide:true})
  let app
  try {
    const version = run(['--version'])
    const directory = /^Install directory: (.+)$/m.exec(version)?.[1]?.trim()
    assert.equal(directory && path.resolve(directory).toLowerCase(),path.join(payload,stamp.runtime.repoDir).toLowerCase(), 'CLI must execute the embedded source')
    const output = run(['gateway','ensure','--json'])
    const records = output.split(/\r?\n/).flatMap(line => {try{return [JSON.parse(line)]}catch{return []}})
    const ready = records.find(record => record.state==='ready')
    assert.ok(ready?.endpoint, 'Actual embedded gateway must become ready')
    assert.equal(ready.endpoint.code_sha,commit,'Running core must match the packaged commit')
    const { _electron } = await import('@playwright/test')
    app = await _electron.launch({executablePath:executable,args:['--disable-gpu'],env,timeout:90000})
    const page = await app.firstWindow()
    await page.waitForLoadState('domcontentloaded')
    await page.waitForFunction(() => (document.querySelector('#root')?.textContent?.trim().length ?? 0)>10,{},{timeout:90000})
    const identity = await app.evaluate(({app}) => ({version:app.getVersion(),data:app.getPath('userData')}))
    assert.equal(identity.version,'0.1.0-rc.1')
    assert.equal(path.resolve(identity.data),path.resolve(env.HERMES_DESKTOP_USER_DATA_DIR))
    await page.screenshot({path:path.join(scratch,'installed-rc.png')})
    const result={status:'passed',commit,version:identity.version,payload:'bundled',
      channel:'meu-rc',realGatewayStartup:true,rendererLaunched:true,cloudModelTested:false}
    fs.writeFileSync(path.join(scratch,'result.json'),JSON.stringify(result,null,2)+'\n')
    console.log('PASS: installed RC identity, embedded CLI, real gateway and isolated renderer')
  } finally {
    if(app) await app.close()
    run(['gateway','stop'])
  }
}
if (process.argv[1] && import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href) await main()
