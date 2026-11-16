import {test} from 'node:test'
import assert from 'node:assert/strict'
import {noPublishArguments} from '../../apps/desktop/scripts/run-electron-builder.mjs'
test('publishing stays disabled with an explicit never policy',()=>{
  assert.deepEqual(noPublishArguments(['--win','nsis','--publish','never']),['--win','nsis','--publish','never'])
})
test('repeated never flags cannot become a truthy publish-policy array',()=>{
  assert.deepEqual(noPublishArguments(['--win','nsis','--publish','never','--publish','never']),['--win','nsis','--publish','never'])
})
test('short and equals forms produce one never policy',()=>{
  assert.deepEqual(noPublishArguments(['-p','never','--publish=never','--x64']),['--x64','--publish','never'])
})
test('an omitted policy is explicitly disabled',()=>assert.deepEqual(noPublishArguments(['--dir']),['--dir','--publish','never']))
test('a request to publish is refused',()=>{
  for(const value of ['always','onTag','onTagOrDraft']) assert.throws(()=>noPublishArguments(['--publish',value]),/release adapter/)
})
