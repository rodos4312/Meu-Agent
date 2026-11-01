// Standalone Meu state-isolation smoke: node scripts/test-meu-isolation.mjs
import assert from 'node:assert/strict'
import { resolveMeuHome } from '../electron/data-paths.mjs'

const windows = {
  LOCALAPPDATA: 'C:\\Users\\Akati\\AppData\\Local',
  HERMES_HOME: 'D:\\ExistingHermes',
  HERMES_DATA_DIR_SUFFIX: '-old',
  HERMES_DESKTOP_USER_DATA_DIR: 'D:\\HermesUI'
}
const expected = 'C:\\Users\\Akati\\AppData\\Local\\MeuAgent'
assert.equal(resolveMeuHome('C:\\Users\\Akati', windows, 'win32'), expected)
assert.equal(resolveMeuHome('C:\\Users\\Akati', { ...windows, HERMES_HOME: 'Z:\\OtherHermes' }, 'win32'), expected)
assert.equal(resolveMeuHome('C:\\Users\\Akati', { ...windows, MEU_HOME: 'D:\\MeuData' }, 'win32'), 'D:\\MeuData')
assert.equal(resolveMeuHome('/home/akati', { HERMES_HOME: '/home/akati/.hermes' }, 'linux'), '/home/akati/.meu')
console.log('Meu independent data roots: PASS')
