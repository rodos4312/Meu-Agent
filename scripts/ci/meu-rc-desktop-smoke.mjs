import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { execFileSync } from 'node:child_process'
import { pathToFileURL } from 'node:url'
import {startBootstrapRuntime} from './meu-bootstrap-runtime.mjs'

export function validateRcStamp(stamp, expected, branch = 'rc/meu-independence-rc1', payload = 'bundled', repository = 'rodos4312/Meu-Agent-RC-private') {
  assert.equal(stamp.commit, expected)
  assert.equal(stamp.dirty, false)
  assert.equal(stamp.payload, payload)
  assert.equal(stamp.branch, branch)
  assert.equal(stamp.meuUpdates.repository, repository)
  assert.equal(stamp.meuUpdates.channel, repository === 'rodos4312/Meu-Agent' ? 'meu-preview' : 'meu-rc')
  assert.equal(stamp.meuUpdates.branch, stamp.branch)
  if(payload==='bootstrap') {
    assert.equal(stamp.updateMechanism,'app-installer')
    assert.equal(stamp.sourceSeed.commit,expected)
    assert.equal(stamp.sourceSeed.repository,`https://github.com/${repository}.git`)
    assert.match(stamp.sourceSeed.sha256,/^[a-f0-9]{64}$/)
  } else assert.ok(stamp.runtime.repoDir && stamp.runtime.commands.hermes)
}

async function main() {
  const [executable, scratch, commit] = process.argv.slice(2)
  assert.equal(process.env.GITHUB_ACTIONS, 'true', 'Disposable CI only')
  const resources = path.join(path.dirname(executable), 'resources')
  const stamp = JSON.parse(fs.readFileSync(path.join(resources, 'install-stamp.json'), 'utf8'))
  const branch = process.env.GITHUB_REF_NAME
  const repository=process.env.GITHUB_REPOSITORY || 'rodos4312/Meu-Agent-RC-private'
  assert.ok(repository==='rodos4312/Meu-Agent' ? branch==='dev/meu-foundation' : branch?.startsWith('rc/'), 'An admitted source ref is required')
  const small=process.env.MEU_SOURCE_SEED==='1'
  validateRcStamp(stamp, commit, branch, small?'bootstrap':'bundled', repository)
  const payload = path.join(resources, 'agent-payload')
  if(!small) {
    const embedded = JSON.parse(fs.readFileSync(path.join(payload, stamp.runtime.repoDir, 'install-stamp.json'), 'utf8'))
    validateRcStamp(embedded, commit, branch)
  }
  assert.ok(fs.existsSync(path.join(resources, 'open-source-notices/Hermes-LICENSE.txt')))
  assert.ok(fs.existsSync(path.join(resources, 'open-source-notices/electron-builder-LICENSE.txt')))
  fs.mkdirSync(scratch, {recursive:true})
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
    !/(?:API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIALS|PRIVATE_KEY)$/.test(key) &&
    !['PYTHONHOME','PYTHONPATH','VIRTUAL_ENV','HERMES_PYTHON','HERMES_PYTHON_SRC_ROOT','HERMES_DESKTOP_BOOT_FAKE','HERMES_RUNTIME_DIR','ELECTRON_RUN_AS_NODE','HERMES_DESKTOP_DEV_SERVER','HERMES_DESKTOP_HERMES','HERMES_DESKTOP_HERMES_ROOT','HERMES_DESKTOP_PYTHON'].includes(key)))
  Object.assign(env, {MEU_HOME:path.join(scratch,'profile'),HERMES_HOME:path.join(scratch,'profile'),
    HERMES_DESKTOP_USER_DATA_DIR:path.join(scratch,'desktop'),HERMES_DESKTOP_SKIP_PROTOCOL_REGISTRATION:'1',
    HERMES_DESKTOP_SKIP_QUIT_CONFIRM:'1',MEU_AGENT_MODE:'1',PYTHONUTF8:'1'})
  if(small && !fs.existsSync(path.join(env.HERMES_HOME,'meu-agent','.hermes-bootstrap-complete'))) env.HERMES_DESKTOP_IGNORE_EXISTING='1'
  let cli = small ? null : path.join(payload, stamp.runtime.commands.hermes)
  const run = args => execFileSync(cli,args,{env,cwd:scratch,encoding:'utf8',timeout:180000,windowsHide:true})
  let app, page
  try {
    if(small) ({app,page,cli}=await startBootstrapRuntime(executable,scratch,env,stamp))
    const version = run(['--version'])
    const directory = /^Install directory: (.+)$/m.exec(version)?.[1]?.trim()
    assert.equal(directory && path.resolve(directory).toLowerCase(),(small?path.join(env.HERMES_HOME,'meu-agent'):path.join(payload,stamp.runtime.repoDir)).toLowerCase(), 'CLI must execute the exact installed source')
    const output = run(['gateway','ensure','--json'])
    const records = output.split(/\r?\n/).flatMap(line => {try{return [JSON.parse(line)]}catch{return []}})
    const ready = records.find(record => record.state==='ready')
    assert.ok(ready?.endpoint, 'Actual embedded gateway must become ready')
    assert.equal(ready.endpoint.code_sha,commit,'Running core must match the packaged commit')
    const { _electron } = await import('@playwright/test')
    if(!app) app = await _electron.launch({executablePath:executable,args:['--disable-gpu'],env,timeout:90000})
    app.context().setDefaultTimeout(90000)
    page = await app.firstWindow({timeout:90000})
    await page.emulateMedia({reducedMotion:'reduce'})
    let successfulRpc=false, skippedSetup=false, rendererState
    page.on('websocket', socket => socket.on('framereceived', ({payload}) => {
      try {
        const packet=JSON.parse(String(payload))
        if(packet.jsonrpc==='2.0' && packet.id!=null && 'result' in packet && !packet.error) successfulRpc=true
      } catch { /* Non-JSON socket frames do not prove gateway readiness. */ }
    }))
    await page.reload({waitUntil:'domcontentloaded',timeout:90000})
    const deadline=Date.now()+180000
    while(Date.now()<deadline) {
      // Use the normal first-run escape; never seed fake credentials or backend state.
      const later=page.getByRole('button',{name:/^(Continue without setup|I'll choose a provider later)$/i})
      for(const button of await later.all()) {
        if(await button.isVisible()) {
          await button.click({timeout:5000})
          skippedSetup=true
          break
        }
      }
      rendererState=await page.evaluate(() => {
        const shown=e => !!e && e.checkVisibility({opacityProperty:true,visibilityProperty:true})
        const interactive=e => {
          if(!shown(e)) return false
          const rect=e.getBoundingClientRect()
          const hit=document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2)
          return !!hit && (hit===e || e.contains(hit))
        }
        const connecting=[...document.querySelectorAll('[data-glass-opaque]')].some(e =>
          e.classList.contains('z-(--z-connecting)') && shown(e))
        const composer=[...document.querySelectorAll('[data-slot="composer-rich-input"]')].some(interactive)
        const providerInput=[...document.querySelectorAll('input[type="password"]')].some(interactive)
        const lookingUpProviders=[...document.querySelectorAll('[role="status"]')].some(e =>
          shown(e) && /Looking up providers/i.test(e.textContent ?? ''))
        return {connecting,composer,providerInput,lookingUpProviders,
          bridge:typeof window.hermesDesktop?.getConnection==='function'}
      })
      if(successfulRpc && rendererState.bridge && !rendererState.connecting &&
         !rendererState.lookingUpProviders && (rendererState.composer || rendererState.providerInput)) break
      await page.waitForTimeout(1000)
    }
    fs.writeFileSync(path.join(scratch,'renderer-state.json'),JSON.stringify({
      ...rendererState,successfulRpc,skippedSetup,cloudModelTested:false},null,2)+'\n')
    await page.screenshot({path:path.join(scratch,'installed-rc.png')})
    assert.ok(successfulRpc && rendererState?.bridge && !rendererState.connecting &&
      !rendererState.lookingUpProviders && (rendererState.composer || rendererState.providerInput),
      'Authenticated core replies and an unobscured interactive application surface are required')
    const identity = await app.evaluate(({app}) => ({version:app.getVersion(),data:app.getPath('userData')}))
    assert.equal(identity.version,process.env.HERMES_PAYLOAD_VERSION)
    assert.equal(path.resolve(identity.data),path.resolve(env.HERMES_DESKTOP_USER_DATA_DIR))
    await page.screenshot({path:path.join(scratch,'installed-rc.png')})
    const result={status:'passed',commit,version:identity.version,payload:stamp.payload,automaticBootstrap:small,
      channel:stamp.meuUpdates.channel,realGatewayStartup:true,rendererLaunched:true,
      interactiveRenderer:true,successfulRpc,skippedSetup,rendererState,cloudModelTested:false}
    fs.writeFileSync(path.join(scratch,'result.json'),JSON.stringify(result,null,2)+'\n')
    console.log('PASS: installed RC identity, embedded CLI, real gateway and isolated renderer')
  } catch(error) {
    if(page) await page.screenshot({path:path.join(scratch,'failed-application.png')}).catch(()=>{})
    throw error
  } finally {
    if(app) await app.close()
    if(cli) run(['gateway','stop'])
  }
}
if (process.argv[1] && import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href) await main()
