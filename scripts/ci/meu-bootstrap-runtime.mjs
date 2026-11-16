// Exercise the installed application's own bootstrap, with no GitHub token.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import {execFileSync} from 'node:child_process'

export async function startBootstrapRuntime(executable, scratch, env, stamp) {
  const {_electron}=await import('@playwright/test')
  const app=await _electron.launch({executablePath:executable,args:['--disable-gpu'],env,timeout:90000})
  const page=await app.firstWindow({timeout:90000})
  const root=path.join(env.HERMES_HOME,'meu-agent')
  const marker=path.join(root,'.hermes-bootstrap-complete')
  const deadline=Date.now()+20*60*1000
  try {
    while(Date.now()<deadline) {
      const body=await page.locator('body').innerText({timeout:10000}).catch(()=> '')
      if (/Update did not finish|Failed to download install|Setup failed/i.test(body)) {
        throw new Error('Real application bootstrap failed: '+body.slice(-4000))
      }
      if(fs.existsSync(marker)) {
        const head=execFileSync('git',['-C',root,'rev-parse','HEAD'],{encoding:'utf8',windowsHide:true}).trim()
        if(head===stamp.commit) {
          const candidates=['hermes.exe','hermes.cmd'].map(name=>path.join(root,'.hermes','bin',name))
          const cli=candidates.find(file=>fs.existsSync(file))
          assert.ok(cli,'Bootstrap must publish its own installation launcher')
          fs.writeFileSync(path.join(scratch,'bootstrap-result.json'),JSON.stringify({
            status:'passed',commit:head,automaticBootstrap:true,privateGithubToken:false,
            sourceSeedSha256:stamp.sourceSeed.sha256,root
          },null,2)+'\n')
          return {app,page,cli,root}
        }
      }
      await page.waitForTimeout(1000)
    }
    throw new Error('Real application bootstrap did not complete within 20 minutes')
  } catch(error) {
    await page.screenshot({path:path.join(scratch,'bootstrap-failed.png')}).catch(()=>{})
    await app.close()
    throw error
  }
}
