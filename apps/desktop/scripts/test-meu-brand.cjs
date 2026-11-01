// Small identity contract, runnable without installing UI dependencies:
// node apps/desktop/scripts/test-meu-brand.cjs
'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { createRequire } = require('node:module')

const root = path.join(__dirname, '..')
const identityPath = path.join(root, 'product-identity.cjs')
const main = require(identityPath)
const pkg = require(path.join(root, 'package.json'))
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8')

assert.equal(main.displayName, 'Meu')
assert.equal(main.appId, 'com.meuagent.desktop')
assert.equal(main.appNamePascal, 'Meu')
assert.equal(main.windowsExecutableName, 'Meu')
assert.equal(main.channel, null, 'No upstream Hermes update feed for Meu')
assert.equal(main.cliName, 'hermes', 'Backend CLI remains compatible')
assert.equal(pkg.productName, 'Meu')
assert.match(html, /<title>Meu<\/title>/)
// Guard the English copy the desktop actually ships, rather than only the
// package metadata. Source identifiers may still carry Hermes protocol names.
for (const relative of [
  'src/i18n/en.ts',
  'src/i18n/en_boot.ts',
  'src/i18n/en_gateway_host.ts',
  'src/i18n/en_onboarding.ts',
  'src/i18n/en_first_run.ts',
  'src/components/chat/intro-copy.jsonl'
]) {
  const copy = fs.readFileSync(path.join(root, relative), 'utf8')
  assert.doesNotMatch(copy, /\\bHermes\\b/, `Visible upstream name remains in ${relative}`)
}
assert.match(fs.readFileSync(path.join(root, 'src/components/chat/intro.tsx'), 'utf8'), /WORDMARK = 'MEU'/)

const lightModule = { exports: {} }
vm.runInNewContext(fs.readFileSync(identityPath, 'utf8'), {
  module: lightModule,
  require: createRequire(identityPath),
  process: { env: { ...process.env, HERMES_DESKTOP_VARIANT: 'light' } }
}, { filename: identityPath })
const light = lightModule.exports
assert.equal(light.displayName, 'Hermes Light', 'Unrelated upstream variant must not be renamed')

process.stdout.write('Meu desktop identity smoke: PASS\n')
