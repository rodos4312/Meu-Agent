import {test} from 'node:test'
import assert from 'node:assert/strict'
import {validateRcStamp} from './meu-rc-desktop-smoke.mjs'
const commit='4'.repeat(40)
function valid(){return {commit,dirty:false,payload:'bundled',branch:'rc/meu-independence-rc1',
  meuUpdates:{repository:'rodos4312/Meu-Agent-RC-private',channel:'meu-rc',branch:'rc/meu-independence-rc1'},
  runtime:{repoDir:'hermes-agent',commands:{hermes:'bin/meu.exe'}}}}
test('accepts a complete private RC pinned to the expected commit',()=>validateRcStamp(valid(),commit))
test('refuses an older embedded core',()=>assert.throws(()=>validateRcStamp({...valid(),commit:'5'.repeat(40)},commit)))
test('refuses a public update identity',()=>{const stamp=valid();stamp.meuUpdates.repository='rodos4312/Meu-Agent';assert.throws(()=>validateRcStamp(stamp,commit))})
test('refuses a bootstrap-only package',()=>assert.throws(()=>validateRcStamp({...valid(),payload:'bootstrap'},commit)))
test('refuses an uncommitted source build',()=>assert.throws(()=>validateRcStamp({...valid(),dirty:true},commit)))
test('refuses a missing embedded launcher',()=>{const stamp=valid();delete stamp.runtime.commands.hermes;assert.throws(()=>validateRcStamp(stamp,commit))})
