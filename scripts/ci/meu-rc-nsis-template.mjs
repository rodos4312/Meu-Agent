import fs from 'node:fs'
import path from 'node:path'
import assert from 'node:assert/strict'
import {createRequire} from 'node:module'
import {spawnSync} from 'node:child_process'
assert.equal(process.env.GITHUB_ACTIONS,'true','Synthetic packaging is CI-only')
const root=process.cwd()
const require=createRequire(path.join(root,'apps/desktop/package.json'))
const packageRoot=path.dirname(path.dirname(require.resolve('electron-builder')))
const cli=path.join(packageRoot,'cli.js')
const dummy=path.join(root,'fixture-output/synthetic-app')
const output=path.join(root,'fixture-output/template-build')
fs.mkdirSync(path.join(dummy,'resources'),{recursive:true})
// A test executable checks NSIS compilation only. It is never installed or released.
fs.copyFileSync(path.join(root,'fixture-output/fixed-bootstrap.exe'),path.join(dummy,'Meu.exe'))
fs.writeFileSync(path.join(dummy,'TEST-ONLY.txt'),'Synthetic compiler fixture. Not the MEU application.\n')
const result=spawnSync(process.execPath,[cli,'--projectDir',path.join(root,'apps/desktop'),
 '--config','electron-builder.config.cjs','--prepackaged',dummy,'--win','nsis','--x64',
 '--publish','never',`-c.directories.output=${output}`],{
 cwd:path.join(root,'apps/desktop'),env:{...process.env,HERMES_DESKTOP_VARIANT:'bundled',MEU_UPDATE_CHANNEL:'rc'},
 stdio:'inherit',windowsHide:true,timeout:180000
})
if(result.error)throw result.error
assert.equal(result.status,0,'The full production NSIS template must compile with the custom hook')
assert.ok(fs.readdirSync(output).some(name=>name.endsWith('-win-x64.exe')))
fs.writeFileSync(path.join(root,'fixture-output/template-result.json'),JSON.stringify({
 status:'passed',fullProductionTemplateCompiled:true,syntheticExecutable:true,
 executableInstalled:false,releaseArtifact:false,publishingDisabled:true
},null,2)+'\n')
console.log('PASS: the complete production NSIS template compiles with the real custom include order')
