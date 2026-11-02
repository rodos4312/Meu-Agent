'use strict'

const { createPublicKey, sign, verify } = require('node:crypto')

// Explicit field order is the wire format. Never sign arbitrary JSON serialization.
function releaseBytes(release) {
  return Buffer.from(
    JSON.stringify([
      'Meu Windows update v2',
      release.schema,
      release.repository,
      release.branch,
      release.channel,
      release.version,
      release.commit,
      release.publisherName,
      release.file,
      release.size,
      release.sha256,
      release.sha512
    ]),
    'utf8'
  )
}

function publicKey(value) {
  if (typeof value !== 'string' || !/^[A-Za-z0-9+/]{59}=$/.test(value)) {
    throw new Error('Invalid Meu Ed25519 public key.')
  }
  const key = createPublicKey({ key: Buffer.from(value, 'base64'), format: 'der', type: 'spki' })
  if (key.asymmetricKeyType !== 'ed25519') throw new Error('Meu updates require an Ed25519 key.')
  return key
}

function verifyRelease(release, pinnedKey) {
  if (
    release.schema !== 2 ||
    release.publisherName !== '' ||
    typeof release.signature !== 'string' ||
    !/^[A-Za-z0-9+/]{86}==$/.test(release.signature) ||
    !verify(null, releaseBytes(release), publicKey(pinnedKey), Buffer.from(release.signature, 'base64'))
  ) {
    throw new Error('Meu update signature does not match the installed trusted key.')
  }
}

function signRelease(release, privateKey, pinnedKey) {
  const signed = { ...release, signature: sign(null, releaseBytes(release), privateKey).toString('base64') }
  verifyRelease(signed, pinnedKey)
  return signed
}

module.exports = { publicKey, verifyRelease, signRelease }
