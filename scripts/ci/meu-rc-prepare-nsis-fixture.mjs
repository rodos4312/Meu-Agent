import fs from 'node:fs'
import path from 'node:path'
import {createRequire} from 'node:module'
import {pathToFileURL} from 'node:url'
const require=createRequire(path.resolve('apps/desktop/package.json'))
const packageRoot=path.dirname(path.dirname(require.resolve('app-builder-lib')))
const {getMakeNsisPath}=await import(pathToFileURL(path.join(packageRoot,'dist/toolsets/nsis.js')).href)
const tool=await getMakeNsisPath(undefined,path.resolve('apps/desktop/assets'))
fs.mkdirSync('fixture-output',{recursive:true})
fs.writeFileSync('fixture-output/compiler.json',JSON.stringify(tool,null,2))
const source=fs.readFileSync(path.join(packageRoot,'templates/nsis/uninstaller.nsh'),'utf8')
const body=source.slice(source.indexOf('Function un.atomicRMDir'),source.indexOf('!ifndef UNINSTALL_SECTION_NAME'))
if(!body.includes('Function un.restoreFiles'))throw new Error('Upstream fixture unavailable')
fs.writeFileSync('fixture-output/upstream-removal.nsh',body)
console.log('Prepared the pinned vendor compiler and original executable comparison fixture')
