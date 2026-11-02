import fs from 'node:fs'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { load, dump } from 'js-yaml'
import { valid } from 'semver'
import { isMain } from './utils.mjs'
import policy from '../meu-release.cjs'
import signing from '../meu-release-signing.cjs'

function validateStamp(stamp) {
  const updates = stamp.meuUpdates
  if (
    !updates ||
    updates.repository !== policy.REPOSITORY ||
    updates.branch !== policy.BRANCH ||
    updates.channel !== policy.CHANNEL ||
    (updates.publicKey ? Boolean(updates.publisherName) : !updates.publisherName?.startsWith('CN=')) ||
    stamp.branch !== policy.BRANCH ||
    stamp.dirty ||
    !/^[a-f0-9]{40}$/.test(stamp.commit)
  ) {
    throw new Error('Release requires a clean, pinned Meu development build and its own publisher.')
  }
  if (updates.publicKey) signing.publicKey(updates.publicKey)
  return updates
}

function validateScan(report, name, bytes, sha256, sha512, updates, version) {
  const validSignature = updates.publicKey
    ? report.signature?.status === 'NotSigned'
    : report.signature?.status === 'Valid' &&
      report.signature.type === 'Authenticode' &&
      report.signature.subject === updates.publisherName
  if (
    report.status !== 'clean' ||
    report.file !== name ||
    report.productVersion !== version ||
    report.sha256 !== sha256 ||
    report.sha512 !== sha512 ||
    report.bytes !== bytes.length ||
    !Array.isArray(report.scans) ||
    report.scans.length < 2 ||
    report.scans.some(scan => scan.exitCode !== 0) ||
    !validSignature
  ) {
    throw new Error('Meu release has missing or mismatched malware/signature evidence.')
  }
}

/** Consume completed scan/signature evidence, never a successful build alone. */
export function prepareMeuRelease({ installer, report, stamp, version, feed, output, privateKey }) {
  if (!valid(version)) throw new Error('Invalid Meu release version.')
  const updates = validateStamp(stamp)
  const name = `Meu-${version}-win-x64.exe`
  if (path.basename(installer) !== name) throw new Error('Installer filename differs from its Meu release version.')
  const bytes = fs.readFileSync(installer)
  const sha256 = createHash('sha256').update(bytes).digest('hex')
  const sha512 = createHash('sha512').update(bytes).digest('base64')
  validateScan(report, name, bytes, sha256, sha512, updates, version)
  const metadata = load(fs.readFileSync(feed, 'utf8'))
  if (
    metadata?.version !== version ||
    metadata.files?.length !== 1 ||
    metadata.files[0].url !== name ||
    metadata.files[0].sha512 !== sha512
  ) {
    throw new Error('Native feed differs from the scanned Meu installer.')
  }
  metadata.files[0].size = bytes.length
  let manifest = {
    schema: updates.publicKey ? 2 : 1,
    repository: updates.repository,
    branch: updates.branch,
    channel: updates.channel,
    publisherName: updates.publisherName || '',
    version,
    commit: stamp.commit,
    file: name,
    size: bytes.length,
    sha256,
    sha512
  }
  if (updates.publicKey) {
    if (!privateKey) throw new Error('Meu release preparation requires its private update key, not a paid certificate.')
    manifest = signing.signRelease(manifest, privateKey, updates.publicKey)
  }
  fs.mkdirSync(output, { recursive: true })
  fs.copyFileSync(installer, path.join(output, name))
  fs.writeFileSync(path.join(output, 'meu-release.json'), JSON.stringify(manifest, null, 2) + '\n')
  fs.writeFileSync(path.join(output, `${policy.CHANNEL}.yml`), dump(metadata))
  fs.writeFileSync(path.join(output, 'meu-package-security.json'), JSON.stringify(report, null, 2) + '\n')
  fs.writeFileSync(path.join(output, 'SHA256SUMS.txt'), `${sha256}  ${name}\n`)
  return manifest
}

if (isMain(import.meta.url)) {
  const root = path.resolve(import.meta.dirname, '..')
  const version = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')).version
  const manifest = prepareMeuRelease({
    installer: path.join(root, 'release', `Meu-${version}-win-x64.exe`),
    privateKey: process.env.MEU_RELEASE_PRIVATE_KEY,
    version,
    report: JSON.parse(fs.readFileSync(path.join(root, 'release/security/meu-package-security.json'), 'utf8')),
    stamp: JSON.parse(fs.readFileSync(path.join(root, 'build/install-stamp.json'), 'utf8')),
    feed: path.join(root, `release/${policy.CHANNEL}.yml`),
    output: path.join(root, 'release/meu-release-candidate')
  })
  console.log(`Prepared verified Meu release ${manifest.version} at ${manifest.commit}. Publication remains a draft.`)
}
