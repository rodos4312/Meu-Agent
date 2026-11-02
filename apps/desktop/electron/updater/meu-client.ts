import electronUpdater from 'electron-updater'

import releasePolicy from '../../meu-release.cjs'
import signing from '../../meu-release-signing.cjs'
import type { InstallStamp } from '../install-stamp'
import { verifyPinnedArtifact } from './artifact'
import { retainMeuInstaller } from './meu-recovery'
import { findMeuRelease, meuReleaseDirectory, validateMeuRelease, type MeuRelease } from './meu-release-feed'
import { verifyMeuSignature } from './meu-signature'
import { MeuWindowsStrategy, type MeuWindowsDeps } from './meu-windows'

interface MeuClientDeps extends Pick<MeuWindowsDeps, 'prepare' | 'teardown' | 'restore' | 'emitProgress'> {
  stamp: Readonly<InstallStamp> | null
  currentVersion: string
  executable: string
  recoveryDirectory: string
  log: (message: string) => void
}

export async function createMeuWindowsStrategy(deps: MeuClientDeps): Promise<MeuWindowsStrategy> {
  const policy = deps.stamp?.meuUpdates
  if (
    policy &&
    (policy.repository !== releasePolicy.REPOSITORY ||
      policy.branch !== releasePolicy.BRANCH ||
      policy.channel !== releasePolicy.CHANNEL)
  ) {
    throw new Error('This artifact has an invalid Meu update authority.')
  }
  const publisher = policy?.publisherName ?? null
  const authority = policy?.publicKey ?? publisher
  if (policy && Boolean(policy.publicKey) === Boolean(policy.publisherName)) {
    throw new Error('Meu requires exactly one trusted update identity.')
  }
  if (policy?.publicKey) signing.publicKey(policy.publicKey)
  if (publisher) await verifyMeuSignature(deps.executable, publisher, deps.currentVersion)
  const verifyInstaller = async (file: string, release: MeuRelease): Promise<void> => {
    validateMeuRelease(release, release.version, authority!)
    await verifyPinnedArtifact(file, { url: '', sha256: release.sha256, size: release.size, format: 'exe' })
    if (publisher) await verifyMeuSignature(file, publisher, release.version)
  }
  return new MeuWindowsStrategy({
    ...deps,
    publisher: authority,
    findRelease: () => findMeuRelease(deps.currentVersion, authority!),
    verifySignature: verifyInstaller,
    retain: (file, release) =>
      retainMeuInstaller(deps.recoveryDirectory, file, release, deps.currentVersion, authority!),
    native: release => {
      let handedOff = false
      const updater = new electronUpdater.NsisUpdater({
        provider: 'generic',
        url: meuReleaseDirectory(release.version),
        channel: releasePolicy.CHANNEL
      })
      updater.autoDownload = false
      updater.autoInstallOnAppQuit = false
      updater.autoRunAppAfterInstall = true
      updater.disableWebInstaller = true
      updater.disableDifferentialDownload = true
      updater.allowPrerelease = true
      updater.allowDowngrade = false
      // No per-user staging identifier is sent to the public release host.
      updater.requestHeaders = { 'x-user-staging-id': '' }
      updater.on('download-progress', event =>
        deps.emitProgress({ stage: 'fetch', message: 'Downloading the verified Meu release.', percent: event.percent })
      )
      updater.on('error', error => {
        deps.log(`Meu updater: ${error.message}`)
        if (handedOff) {
          handedOff = false
          deps.emitProgress({ stage: 'error', message: error.message, percent: null })
          void deps.restore().catch(restoreError => deps.log(`Meu update recovery: ${restoreError.message}`))
        }
      })
      // Enforce our verifier even when native verification is unavailable or permissive.
      updater.verifyUpdateCodeSignature = async (_names, file) => {
        await verifyInstaller(file, release)
        return null
      }
      return {
        checkForUpdates: () => updater.checkForUpdates(),
        downloadUpdate: () => updater.downloadUpdate(),
        quitAndInstall: () => {
          handedOff = true
          try {
            updater.quitAndInstall(false, true)
          } catch (error) {
            handedOff = false
            throw error
          }
        }
      }
    }
  })
}
