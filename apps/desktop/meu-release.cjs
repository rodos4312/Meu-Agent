'use strict'

const REPOSITORY = 'rodos4312/Meu-Agent'
const BRANCH = 'dev/meu-foundation'
const CHANNEL = 'meu-preview'
const updateKey = require('./meu-update-key.json')
const { publicKey } = require('./meu-release-signing.cjs')

/** Build-only signing inputs; credentials never enter the artifact stamp. */
function meuReleasePolicy(env = process.env) {
  if (env.MEU_SIGNED_RELEASE !== '1') {
    publicKey(updateKey.publicKey)
    return { repository: REPOSITORY, branch: BRANCH, channel: CHANNEL, publicKey: updateKey.publicKey }
  }
  const publisherName = (env.MEU_WINDOWS_PUBLISHER || '').trim()
  if (!publisherName.startsWith('CN=') || /[\r\n\x00]/.test(publisherName)) {
    throw new Error('A signed Meu release requires its own full Windows certificate subject (MEU_WINDOWS_PUBLISHER).')
  }
  if (env.AZURE_SIGN_ENDPOINT || env.AZURE_CLIENT_ID) {
    throw new Error('Meu releases cannot use the upstream Azure signing identity.')
  }
  return { repository: REPOSITORY, branch: BRANCH, channel: CHANNEL, publisherName }
}

module.exports = { REPOSITORY, BRANCH, CHANNEL, meuReleasePolicy }
