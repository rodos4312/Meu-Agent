'use strict'

const updateKey = require('./meu-update-key.json')
const { publicKey } = require('./meu-release-signing.cjs')

/**
 * The two Meu update channels: the only source of their identities. Each manifest names its channel's
 * repository, branch and channel, and the signature covers all three, so a release from one channel
 * never validates for the other. `channel` is the wire name in signed manifests and the native feed
 * (stable keeps the historic `meu-preview` so installed builds keep verifying). RC lives in a private
 * repository: it is never an automatic update source (see electron/updater/meu-channel.ts).
 */
const UPDATE_CHANNELS = Object.freeze({
  stable: Object.freeze({
    id: 'stable',
    repository: 'rodos4312/Meu-Agent',
    branch: 'dev/meu-foundation',
    branchPrefix: false,
    channel: 'meu-preview',
    tagPrefix: 'meu-v',
    versionPattern: /^\d+\.\d+\.\d+(?:-dev\.\d+)?$/,
    private: false
  }),
  rc: Object.freeze({
    id: 'rc',
    repository: 'rodos4312/Meu-Agent-RC-private',
    branch: 'rc/',
    branchPrefix: true,
    channel: 'meu-rc',
    tagPrefix: 'meu-rc-v',
    versionPattern: /^\d+\.\d+\.\d+-rc\.\d+$/,
    private: true
  })
})

const STABLE = UPDATE_CHANNELS.stable
// Stable identity, kept for the stable-only release tooling (prepare/maintenance scripts).
const REPOSITORY = STABLE.repository
const BRANCH = STABLE.branch
const CHANNEL = STABLE.channel

/**
 * The channel a build is stamped for: `MEU_UPDATE_CHANNEL` (stable when unset); anything else fails.
 * @param {Record<string, string | undefined>} [env]
 * @returns {'stable' | 'rc'}
 */
function buildUpdateChannel(env = process.env) {
  const value = env.MEU_UPDATE_CHANNEL
  if (value === undefined || value === '') return 'stable'
  if (value !== 'stable' && value !== 'rc') throw new Error(`Unknown Meu update channel: ${value}.`)
  return value
}

/**
 * @param {{ branch: string, branchPrefix: boolean }} spec
 * @param {unknown} branch
 */
function branchAdmitted(spec, branch) {
  if (typeof branch !== 'string') return false
  return spec.branchPrefix
    ? branch.startsWith(spec.branch) && branch.length > spec.branch.length && /^[A-Za-z0-9._/-]+$/.test(branch)
    : branch === spec.branch
}

/**
 * The channel whose identity an install stamp or manifest carries; null for anything foreign.
 * @param {{ repository?: string, branch?: string, channel?: string } | null | undefined} authority
 */
function channelForAuthority(authority) {
  if (!authority) return null
  return Object.values(UPDATE_CHANNELS).find(
    spec => authority.repository === spec.repository && authority.channel === spec.channel && branchAdmitted(spec, authority.branch)
  ) || null
}

/**
 * Build-only signing inputs; credentials never enter the artifact stamp. RC builds pin their own rc/* branch.
 * @param {Record<string, string | undefined>} [env]
 * @param {string | null} [branch]
 */
function meuReleasePolicy(env = process.env, branch = null) {
  const spec = UPDATE_CHANNELS[buildUpdateChannel(env)]
  const admitted = spec.branchPrefix ? branch : spec.branch
  if (env.MEU_SIGNED_RELEASE !== '1') {
    publicKey(updateKey.publicKey)
    return { repository: spec.repository, branch: admitted, channel: spec.channel, publicKey: updateKey.publicKey }
  }
  const publisherName = (env.MEU_WINDOWS_PUBLISHER || '').trim()
  if (!publisherName.startsWith('CN=') || /[\r\n\x00]/.test(publisherName)) {
    throw new Error('A signed Meu release requires its own full Windows certificate subject (MEU_WINDOWS_PUBLISHER).')
  }
  if (env.AZURE_SIGN_ENDPOINT || env.AZURE_CLIENT_ID) {
    throw new Error('Meu releases cannot use the upstream Azure signing identity.')
  }
  return { repository: spec.repository, branch: admitted, channel: spec.channel, publisherName }
}

module.exports = {
  REPOSITORY,
  BRANCH,
  CHANNEL,
  UPDATE_CHANNELS,
  buildUpdateChannel,
  branchAdmitted,
  channelForAuthority,
  meuReleasePolicy
}
